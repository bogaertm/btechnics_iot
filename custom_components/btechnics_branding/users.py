"""Gebruikersbeheer op afstand vanuit de Work-app (v1.35.0).

Overzicht van de gebruikers gaat mee in de status. Opdrachten (via remote.py):
- create_user    naam, gebruikersnaam, wachtwoord (of laten maken), beheerder, enkel lokaal
- update_user    naam, beheerder, actief, enkel lokaal
- set_password   nieuw wachtwoord (of laten maken), eventueel overal afmelden
- logout_user    alle sessies van de gebruiker beeindigen
- delete_user    gebruiker verwijderen

Veiligheidsregels, altijd:
- systeemgebruikers (Supervisor, add-ons) worden nooit getoond of aangepast;
- de eigenaar is onaantastbaar: niet verwijderen, uitschakelen, rechten wijzigen,
  wachtwoord wijzigen of afmelden (enkel de naam mag);
- er blijft altijd minstens een actieve beheerder over;
- een gemaakt wachtwoord gaat eenmalig terug naar de Work-app en wordt nergens in HA gelogd;
- afmelden beeindigt de gewone sessies; langlevende toegangstokens (van integraties)
  blijven, zodat koppelingen niet stilvallen;
- elke actie geeft een melding in HA, zodat de klant ziet wat er gebeurde.
Standaard UIT. Aan te zetten per klant in de instellingen
("Gebruikersbeheer op afstand door Btechnics").
"""
from __future__ import annotations

import re
import secrets
from typing import Any

from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.core import HomeAssistant

CONF_REMOTE_USERS = "remote_users"
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_MIN_PASSWORD = 12


def _username(user) -> str | None:
    for cred in user.credentials:
        if cred.auth_provider_type == "homeassistant":
            return cred.data.get("username")
    return None


def _last_seen(user) -> str | None:
    times = [t.last_used_at for t in user.refresh_tokens.values() if t.last_used_at]
    return max(times).isoformat() if times else None


def _info(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "username": _username(user),
        "admin": user.is_admin,
        "owner": user.is_owner,
        "active": user.is_active,
        "local_only": user.local_only,
        "last_seen": _last_seen(user),
        "sessions": len([t for t in user.refresh_tokens.values() if t.token_type == "normal"]),
    }


async def async_list(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [_info(u) for u in await hass.auth.async_get_users() if not u.system_generated]


def _new_password() -> str:
    return secrets.token_urlsafe(12)  # 16 tekens


def _check_password(pw: str) -> None:
    if len(pw) < _MIN_PASSWORD:
        raise ValueError(f"wachtwoord moet minstens {_MIN_PASSWORD} tekens hebben")


def _bool(cmd: dict, key: str, default: bool | None = None) -> bool:
    value = cmd.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} moet true of false zijn")
    return value


def _groups(user, admin: bool) -> list[str]:
    """Enkel beheerder/gebruiker wisselen; andere groepen (bv. alleen-lezen) blijven."""
    other = [g.id for g in user.groups if g.id not in (GROUP_ID_ADMIN, GROUP_ID_USER)]
    return other + [GROUP_ID_ADMIN if admin else GROUP_ID_USER]


def _logout(hass: HomeAssistant, user, all_tokens: bool = False) -> int:
    """Gewone sessies beeindigen; met all_tokens ook langlevende tokens (bv. na misbruik)."""
    tokens = [t for t in user.refresh_tokens.values()
              if t.token_type == "normal" or (all_tokens and t.token_type == "long_lived_access_token")]
    for token in tokens:
        hass.auth.async_remove_refresh_token(token)
    return len(tokens)


async def _get(hass: HomeAssistant, cmd: dict):
    user = await hass.auth.async_get_user(str(cmd.get("user_id") or ""))
    if user is None or user.system_generated:
        raise ValueError("gebruiker niet gevonden")
    return user


async def _admins_left(hass: HomeAssistant, without) -> int:
    return len([u for u in await hass.auth.async_get_users()
                if not u.system_generated and u.is_active and u.is_admin and u.id != without.id])


async def async_execute(hass: HomeAssistant, kind: str, cmd: dict) -> dict[str, Any]:
    from homeassistant.auth.providers import homeassistant as auth_ha

    provider = auth_ha.async_get_provider(hass)

    if kind == "create_user":
        name = str(cmd.get("name") or "").strip()
        username = str(cmd.get("username") or "").strip().lower()
        if not name or len(name) > 60:
            raise ValueError("naam ontbreekt of is te lang")
        if not _USERNAME_RE.match(username):
            raise ValueError("gebruikersnaam: 3 tot 32 tekens, kleine letters, cijfers, punt, - of _")
        if any(_username(u) == username for u in await hass.auth.async_get_users()):
            raise ValueError(f"gebruikersnaam {username} bestaat al")
        generated = not cmd.get("password")
        if not generated and not isinstance(cmd["password"], str):
            raise ValueError("wachtwoord moet tekst zijn")
        password = _new_password() if generated else cmd["password"]
        _check_password(password)
        admin = _bool(cmd, "admin", False)
        local_only = _bool(cmd, "local_only", False)
        user = await hass.auth.async_create_user(
            name, group_ids=[GROUP_ID_ADMIN if admin else GROUP_ID_USER], local_only=local_only,
        )
        added = False
        try:
            await provider.async_add_auth(username, password)
            added = True
            creds = await provider.async_get_or_create_credentials({"username": username})
            await hass.auth.async_link_user(user, creds)
        except Exception:
            if added:
                try:
                    await provider.async_remove_auth(username)
                except Exception:  # noqa: BLE001
                    pass
            await hass.auth.async_remove_user(user)
            raise
        out = _info(user)
        if generated:
            out["password"] = password  # eenmalig, enkel in het resultaat
        return out

    if kind == "update_user":
        user = await _get(hass, cmd)
        if user.is_owner and any(k in cmd for k in ("admin", "active", "local_only")):
            raise ValueError("de eigenaar kan enkel van naam veranderen")
        kwargs: dict[str, Any] = {}
        if "name" in cmd:
            name = str(cmd["name"] or "").strip()
            if not name or len(name) > 60:
                raise ValueError("naam ontbreekt of is te lang")
            kwargs["name"] = name
        if "admin" in cmd:
            admin = _bool(cmd, "admin")
            if not admin and user.is_admin and await _admins_left(hass, user) == 0:
                raise ValueError("er moet minstens een actieve beheerder overblijven")
            kwargs["group_ids"] = _groups(user, admin)
        if "active" in cmd:
            active = _bool(cmd, "active")
            if not active and user.is_admin and await _admins_left(hass, user) == 0:
                raise ValueError("er moet minstens een actieve beheerder overblijven")
            kwargs["is_active"] = active
        if "local_only" in cmd:
            kwargs["local_only"] = _bool(cmd, "local_only")
        if not kwargs:
            raise ValueError("niets om aan te passen")
        await hass.auth.async_update_user(user, **kwargs)
        return _info(await _get(hass, cmd))

    if kind == "set_password":
        user = await _get(hass, cmd)
        if user.is_owner:
            raise ValueError("het wachtwoord van de eigenaar kan niet vanop afstand gewijzigd worden")
        username = _username(user)
        if not username:
            raise ValueError("deze gebruiker heeft geen wachtwoord bij Home Assistant")
        generated = not cmd.get("password")
        if not generated and not isinstance(cmd["password"], str):
            raise ValueError("wachtwoord moet tekst zijn")
        password = _new_password() if generated else cmd["password"]
        _check_password(password)
        logout = _bool(cmd, "logout", True)
        all_tokens = _bool(cmd, "all_tokens", False)  # eerst alles valideren
        await provider.async_change_password(username, password)
        ended = _logout(hass, user, all_tokens) if logout else 0
        out = {"user_id": user.id, "name": user.name, "username": username, "sessies_beeindigd": ended}
        if generated:
            out["password"] = password
        return out

    if kind == "logout_user":
        user = await _get(hass, cmd)
        if user.is_owner:
            raise ValueError("de eigenaar kan niet vanop afstand afgemeld worden")
        return {"user_id": user.id, "name": user.name,
                "sessies_beeindigd": _logout(hass, user, _bool(cmd, "all_tokens", False))}

    if kind == "delete_user":
        user = await _get(hass, cmd)
        if user.is_owner:
            raise ValueError("de eigenaar kan niet verwijderd worden")
        if user.is_admin and await _admins_left(hass, user) == 0:
            raise ValueError("er moet minstens een actieve beheerder overblijven")
        # Zoals HA zelf (config/auth delete): gebruiker en zijn aanmeldgegevens samen weg
        name = user.name
        await hass.auth.async_remove_user(user)
        return {"user_id": user.id, "name": name, "verwijderd": True}

    raise ValueError(f"onbekende opdracht: {kind}")


KINDS = ("create_user", "update_user", "set_password", "logout_user", "delete_user")

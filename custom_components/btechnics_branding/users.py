"""Gebruikersbeheer op afstand vanuit de Work-app (v1.35.0).

Overzicht van de gebruikers gaat mee in de status. Opdrachten (via remote.py):
- create_user    naam, gebruikersnaam, wachtwoord (of laten maken), beheerder, enkel lokaal
- update_user    naam, gebruikersnaam (v1.44.0), beheerder, actief, enkel lokaal
- set_password   nieuw wachtwoord (of laten maken), eventueel overal afmelden
- logout_user    alle sessies van de gebruiker beeindigen
- delete_user    gebruiker verwijderen
- set_role       rol kiezen: superadmin, admin, medewerker of gebruiker (v1.49.0, roles.py)
  create_user kan ook meteen een rol krijgen ("role").

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
# v1.44.0: de Work-app gebruikt het mailadres als gebruikersnaam. HA zelf eist
# enkel dat de naam genormaliseerd is (strip + casefold) en uniek
# (auth/providers/homeassistant.py, _validate_new_username); tekens of lengte
# beperkt HA niet. Onze regel blijft bewust smal, zodat het een geldige login is
# op elk toestel en in elke app.
_USERNAME_RE = re.compile(r"^[a-z0-9._@+-]{3,64}$")
USERNAME_RULE = "3 tot 64 tekens: kleine letters a tot z, cijfers 0 tot 9, punt, -, _, @ en +"


class CommandError(ValueError):
    """Weigering met een vaste foutcode en de geldende regel (v1.44.0)."""

    def __init__(self, message: str, code: str, rule: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.rule = rule


def _check_username(raw: Any) -> str:
    username = str(raw or "").strip().lower()
    if not _USERNAME_RE.match(username):
        raise CommandError("gebruikersnaam: " + USERNAME_RULE, "username_invalid", USERNAME_RULE)
    return username
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


def _out(hass: HomeAssistant, user) -> dict[str, Any]:
    """v1.49.0: info plus rol."""
    from . import roles
    return {**_info(user), "role": roles.role(hass, user)}


async def async_list(hass: HomeAssistant) -> list[dict[str, Any]]:
    from . import roles
    await roles.async_load(hass)
    return [_out(hass, u) for u in await hass.auth.async_get_users() if not u.system_generated]


def _check_role(raw: Any) -> str:
    from . import roles
    if raw not in roles.ROLES:
        raise ValueError("rol moet " + ", ".join(roles.ROLES) + " zijn")
    return raw


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
        if not name or len(name) > 60:
            raise ValueError("naam ontbreekt of is te lang")
        username = _check_username(cmd.get("username"))
        if any((_username(u) or "").casefold() == username for u in await hass.auth.async_get_users()):
            raise CommandError(f"gebruikersnaam {username} bestaat al", "username_exists")
        generated = not cmd.get("password")
        if not generated and not isinstance(cmd["password"], str):
            raise ValueError("wachtwoord moet tekst zijn")
        password = _new_password() if generated else cmd["password"]
        _check_password(password)
        admin = _bool(cmd, "admin", False)
        role = _check_role(cmd["role"]) if "role" in cmd else None
        if role is not None:
            if "admin" in cmd and admin != (role == "superadmin"):
                raise ValueError("admin en role spreken elkaar tegen")
            admin = role == "superadmin"
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
            from . import roles
            if role in roles.STORED:
                await roles.async_store_role(hass, user.id, role)
        except Exception:
            if added:
                try:
                    await provider.async_remove_auth(username)
                except Exception:  # noqa: BLE001
                    pass
            await hass.auth.async_remove_user(user)
            raise
        from . import roles
        try:
            await roles.async_apply_sidebar(hass, user)
        except Exception:  # noqa: BLE001
            pass  # de zijbalk volgt bij het volgende event of de volgende start
        out = _out(hass, user)
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
        new_username = None
        if "username" in cmd:
            new_username = _check_username(cmd.get("username"))
            if user.is_owner:
                raise ValueError("de gebruikersnaam van de eigenaar kan niet vanop afstand gewijzigd worden")
            current = _username(user)
            if current is None:
                raise ValueError("deze gebruiker heeft geen wachtwoord bij Home Assistant")
            if new_username == current:
                new_username = None
            elif any((_username(u) or "").casefold() == new_username
                     for u in await hass.auth.async_get_users() if u.id != user.id):
                raise CommandError(f"gebruikersnaam {new_username} bestaat al", "username_exists")
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
        if not kwargs and new_username is None:
            raise ValueError("niets om aan te passen")
        if new_username is not None:
            cred = next(c for c in user.credentials if c.auth_provider_type == "homeassistant")
            await provider.async_change_username(cred, new_username)
        if kwargs:
            await hass.auth.async_update_user(user, **kwargs)
        from . import roles
        user = await _get(hass, cmd)
        if roles.is_admin_group(user):
            await roles.async_forget_user(hass, user.id)  # v1.49.0: superadmin, geen opgeslagen rol
        await roles.async_apply_sidebar(hass, user)
        return _out(hass, user)

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
        from . import roles
        await roles.async_forget_user(hass, user.id, removed=True)
        return {"user_id": user.id, "name": name, "verwijderd": True}

    if kind == "set_role":
        from . import roles
        user = await _get(hass, cmd)
        new = _check_role(cmd.get("role"))
        if new == roles.SUPER:
            if not roles.is_admin_group(user):
                await hass.auth.async_update_user(user, group_ids=_groups(user, True))
            await roles.async_forget_user(hass, user.id)
        else:
            if user.is_owner:
                raise ValueError("de eigenaar blijft superadmin")
            # review: naar de groep kijken, een uitgeschakelde beheerder heeft is_admin False
            if roles.is_admin_group(user) and user.is_active and await _admins_left(hass, user) == 0:
                raise ValueError("er moet minstens een actieve beheerder overblijven")
            # review 2: eerst de rol bewaren (faalt dat, dan is er niets veranderd),
            # pas daarna uit de beheerdersgroep
            await roles.async_store_role(hass, user.id, new)
            if roles.is_admin_group(user):
                await hass.auth.async_update_user(user, group_ids=_groups(user, False))
        user = await _get(hass, cmd)
        await roles.async_apply_sidebar(hass, user)
        return _out(hass, user)

    if kind == "set_dashboards":
        from . import roles
        out = await roles.async_set_dashboards(hass, cmd.get("dashboards"))
        return {**out, "name": "dashboards per rol"}

    raise ValueError(f"onbekende opdracht: {kind}")


KINDS = ("create_user", "update_user", "set_password", "logout_user", "delete_user",
         "set_role", "set_dashboards")

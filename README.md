# Btechnics IOT Features

Voegt de **Btechnics IOT** huisstijl en extra functies toe aan je installatie: eigen logo en naam, Btechnics kleuren, instelbare zoom voor desktop en mobiel.

## Instellingen

Instellingen > Apparaten en diensten > Btechnics IOT > Configureren:

| Optie | Standaard |
|---|---|
| Tekst aanmeldscherm en zijbalk | Btechnics IOT |
| Zoom desktop (%) | 80 |
| Zoom mobiel (%) | 85 |
| Grens mobiel/desktop (px) | 870 |
| Klantenlogo (upload, naast het Btechnics logo in zijbalk, aanmeld- en opstartscherm) | geen |
| Grootte klantenlogo (% van het Btechnics logo) | 100 |

## Installatie via HACS

1. HACS → Integraties → ⋮ → Aangepaste opslagplaatsen
2. Voeg toe: `https://github.com/bogaertm/btechnics_iot` — categorie: **Integratie**
3. Zoek "Btechnics IOT" en installeer
4. Herstart de installatie
5. Instellingen → Integraties → + Toevoegen → Btechnics IOT
6. Voeg toe aan `configuration.yaml`:
```yaml
frontend:
  extra_module_url:
    - /btechnics_branding/btechnics-branding.js
```
7. Herstart de installatie opnieuw

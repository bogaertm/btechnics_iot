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

## Automatische updates

In de opties staat **Automatische updates** (standaard uit). Aan betekent: elke nacht op het gekozen uur (standaard 04:00) worden de beschikbare updates geinstalleerd, in deze volgorde: Supervisor, apps, HACS, eventueel firmware van toestellen, en als laatste Core of OS.

- Core enkel vanaf de eerste bugfix van een maand (x.1), nooit een .0, beta of release candidate.
- Back-up voor elke update die dat ondersteunt (Core, OS, apps).
- Geen updates zolang de zelfcontrole een probleem met de branding meldt.
- Core en OS herstarten het systeem, dus hoogstens een van beide per nacht. Na HACS updates volgt een herstart.
- Een update die je zelf overslaat, wordt nooit automatisch geinstalleerd.
- Wat er gebeurd is, staat in Activiteit onder "Btechnics IOT updates".
- Updates die automatisch geinstalleerd worden, zijn verborgen: geen bolletje in de zijbalk en niet bovenaan Instellingen. Mislukt dezelfde versie 2 keer, dan wordt ze niet meer geprobeerd, komt ze weer tevoorschijn en verschijnt er een melding onder Reparaties. Updates die niet automatisch kunnen, blijven altijd zichtbaar.

Service `btechnics_branding.run_updates` start het meteen; met `dry_run: true` zie je enkel wat er zou gebeuren.

## Status naar Btechnics

Vul in de opties de **sleutel van deze klant** in (aan te maken in de Work-app). Dan stuurt de installatie elk uur, en meteen bij een probleem, een korte status naar `https://work.btechnics.be/api/iot/status`: naam, versies, stand van de branding en openstaande of mislukte updates. Geen wachtwoorden, geen toestelgegevens. Zonder sleutel wordt niets verstuurd.

Service `btechnics_branding.send_status` verstuurt meteen en toont wat er verstuurd werd. Het adres moet met https:// beginnen (enkel een lokaal adres mag http). Beide services (`run_updates` en `send_status`) zijn enkel voor beheerders.

## Bediening op afstand

Met een sleutel ingevuld en **Bediening op afstand door Btechnics** aan (standaard aan), haalt de installatie elke minuut opdrachten op bij de Work-app. Er hoeft geen poort open. Enkel deze opdrachten bestaan: automatische updates aan/uit en instellen, de run nu starten (of enkel tonen), een update installeren, overslaan of terugzetten, mislukte pogingen wissen en de status meteen versturen. Al de rest wordt geweigerd. Alles komt in Activiteit onder "Btechnics IOT updates".

## Woordkeuze

In het Nederlands spreekt Home Assistant van "woning", "je huis" en "Welkom thuis". Btechnics IOT maakt daar neutrale woorden van, voor woningen en bedrijven: "Algemeen" in plaats van "Woninginformatie", "Locatienaam", "je locatie", "Welkom!". Andere talen blijven ongemoeid.

## Diagnose en verwijderen

- **Diagnose downloaden** (Instellingen > Apparaten en diensten > Btechnics IOT > drie puntjes): alles wat de integratie weet in een bestand, zonder sleutel. Handig bij support.
- **Verwijderen**: het klantenlogo, de bijgehouden pogingen en alles wat verborgen was, worden opgeruimd.

## Vereisten

Home Assistant 2026.8.0 of nieuwer. Getest op 2026.8.0 en 2026.9.3. Op oudere versies toont onder meer het opstartscherm nog het oorspronkelijke logo.

## Na een update

De branding haakt in op de interne opbouw van het systeem. Daarom zijn er twee vangnetten:

- **Zelfcontrole**: na elke start kijkt de integratie of alle aanpassingen nog werken. Werkt iets niet meer, dan verschijnt er een melding onder Instellingen > Reparaties met wat er stuk is. Het systeem zelf blijft gewoon werken.
- **Compatibiliteitstest**: `tests/compat` start een echte container met de gekozen versie (stable, beta of dev), installeert de integratie en controleert server en interface. Draai die voor je klanten een nieuwe versie laat installeren.

Lokaal testen: `bash tests/compat/run.sh stable` (Docker en Node 22 nodig, eerst `npm install` en `npx playwright install chromium` in `tests/compat`).

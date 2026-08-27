# OEM Remote Support - Session Service

FastAPI servis koji jednim pozivom kreira video sesiju (Agora), pokreće cloud
recording, šalje join link na mejl OEM predstavnika i vraća isti link kao
odgovor (za dugme u mehaničarevoj app-i).

## Setup

```bash
python -m venv venv
source venv/bin/activate   # ili venv\Scripts\activate na Windows-u
pip install -r requirements.txt
cp .env.example .env       # popuni pravim vrednostima
uvicorn main:app --reload --port 8000
```

## Šta ti treba pre nego što proradi

1. **Agora nalog** (agora.io) → napravi projekat → dobijaš `App ID` i
   `App Certificate`.
2. U istom projektu, pod **RESTful API keys**, generišeš `Customer ID` i
   `Customer Secret` (koriste se za Cloud Recording API poziv, ne mešati sa
   App ID/Certificate).
3. **SMTP nalog** za slanje mejlova — za brz test najlakše je Gmail nalog sa
   generisanim App Password-om (Google Account → Security → App passwords).
   Za produkciju, kasnije samo menjaš `SMTP_*` env varijable na SendGrid ili
   AWS SES SMTP kredencijale — kod se ne menja.
4. Postaviš `static/join.html` negde gde je javno dostupan (može i ovaj isti
   servis da ga servira preko FastAPI `StaticFiles`, ili ga hostuješ posebno
   npr. na S3/Vercel) i u njemu zameniš `REPLACE_WITH_AGORA_APP_ID` pravim
   App ID-jem, pa taj URL staviš u `JOIN_PAGE_BASE_URL`.

## Poziv

```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"oem_email": "oem.rep@example.com", "repair_order_id": "RO-1042"}'
```

Odgovor:

```json
{
  "join_link": "https://yourdomain.com/join.html?channel=ro-RO-1042-abc123&token=...&uid=1",
  "channel_name": "ro-RO-1042-abc123",
  "recording_resource_id": "...",
  "recording_sid": "..."
}
```

- `join_link` se vraća app-i (mehaničar) i šalje se na mejl (OEM rep) — isti
  link, oboje se pridružuju istom kanalu.
- Recording počinje odmah pri kreiranju sesije (ne čeka se da neko uđe u
  poziv). Ako želiš da snimanje krene tek kad se neko stvarno pridruži,
  to zahteva dodatni "on user-joined" webhook/event handling — javi ako
  ti treba, dodajem.

## Sledeći koraci (nisu pokriveni u ovoj verziji)

- **Stop recording** endpoint (`/sessions/{channel_name}/stop`) — treba da
  pozove Agora `/stop` REST endpoint sa sačuvanim `resourceId` i `sid`.
  Trebaš negde da ih čuvaš (npr. baza) između start i stop poziva.
- **Storage konfiguracija** za snimke (S3) — trenutno recording ide na
  Agora-in privremeni storage; `storageConfig` blok u `start_cloud_recording`
  treba popuniti kad odlučite gde ide finalna arhiva.
- **Auth** na `/sessions` endpoint-u — trenutno je otvoren, verovatno želiš
  API key ili internu autentikaciju pre produkcije.

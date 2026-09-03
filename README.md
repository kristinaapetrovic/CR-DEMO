# OEM Remote Support - Session Service

Backend servis koji omogućava video poziv uživo između mehaničara i OEM
predstavnika. Kreira video kanal (Agora), generiše link za pridruživanje,
i taj link šalje mejlom OEM predstavniku.

## Kako pozvati - slanje mejla sa linkom

Pošalji POST zahtev na `/sessions`:

```powershell
$body = @{
    oem_email = "oem@example.com"
    repair_order_id = "RO-1234"
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://cr-service.vercel.app/sessions" -Method Post -Body $body -ContentType "application/json"
```

ili preko cURL-a:

```bash
curl -X POST https://cr-service.vercel.app/sessions \
  -H "Content-Type: application/json" \
  -d '{"oem_email": "oem@example.com", "repair_order_id": "RO-1234"}'
```

**Parametri**
- `oem_email` (obavezno) - mejl adresa OEM predstavnika kome se šalje link
- `repair_order_id` (opciono) - broj radnog naloga, ako postoji

Posle poziva, OEM predstavnik dobija mejl sa linkom za ulazak u poziv.

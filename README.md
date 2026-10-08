# Tourista Rwanda — Backend (Django REST API)

REST API for the Tourista Rwanda frontend (`../tourista-rwanda-digital-oasis`).
It replaces the frontend's localStorage mocks with a real database: accounts and
JWT auth, public listings, bookings with the full payment/check-in lifecycle,
notifications, provider company workspaces, and contact/demo forms.

> **New here?** Start with the simple guide in `../tourista-rwanda-digital-oasis/README.md`.
> It explains setup, demo accounts, roles, workflows and how to test everything.

## Quick start (Windows / PowerShell)

```powershell
cd D:\internship\tourista-rwanda-digital-oasis\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # listings, demo accounts, demo bookings
python manage.py runserver 8000
```

Then start the frontend in another terminal:

```powershell
cd D:\internship\tourista-rwanda-digital-oasis\tourista-rwanda-digital-oasis
npm run dev                        # http://localhost:8080, proxies /api -> :8000
```

Django admin: http://127.0.0.1:8000/admin/ (sign in with `admin@tourista.rw`).

Run the tests with `python manage.py test`.

### Demo accounts

All use the password `Tourista@2026` (change with `DEMO_PASSWORD` in `.env`).
The login form has a "Use a demo account" shortcut that fills these in.

| Email | Role | Dashboard |
|---|---|---|
| tourist@tourista.rw | tourist | My bookings |
| hotel@tourista.rw | hotel_owner | Hotel console |
| tour@tourista.rw | tour_operator | Tours |
| restaurant@tourista.rw | restaurant_owner | Restaurant |
| transport@tourista.rw | transport_owner | Transport |
| park@tourista.rw | park_manager | Parks |
| destination@tourista.rw | destination_manager | Destinations |
| culture@tourista.rw | history_culture_manager | History & culture |
| artisan@tourista.rw | artisan | Artisan workshop |
| shop@tourista.rw | shop_owner | Shop & market |
| spa@tourista.rw | spa_manager | Massage & spa |
| admin@tourista.rw | admin (superuser) | Admin + Django admin |

`python manage.py seed_demo --reset` wipes bookings/notifications and reloads the demo
bookings. Demo booking dates are shifted so they stay relative to today.

## Project layout

```
config/       settings, root URLs
core/         enums, error handler, emails, image uploads, admin API, seed_demo command, tests
accounts/     custom User (email login, role, verified email), JWT auth with httpOnly refresh cookie
listings/     public listings, bookable facilities (prices), search, trip planner
bookings/     Booking + Notification; engine.py (pricing + availability), services.py (lifecycle)
providers/    provider workspace: company profile, catalog, availability rules, staff
reviews/      verified guest reviews + provider replies
messaging/    guest ↔ provider conversations
inquiries/    contact messages and demo requests (staff are emailed)
seed_data/    JSON exported from the frontend's src/data (see "Seed data")
```

Emails (booking confirmations, provider alerts, verification, password reset, staff alerts)
print to the `runserver` terminal unless `EMAIL_HOST` is set in `.env`.

## How the frontend uses the API

| Frontend module | Backend |
|---|---|
| `src/lib/api.ts` | fetch wrapper: access token in memory only, refresh via httpOnly cookie, uploads, CSV downloads |
| `src/contexts/AuthContext.tsx` | `/auth/*` (session restored from the cookie on page load) |
| `src/services/bookingStore.ts` | `/bookings/*`, `/availability/`, `/notifications/*` |
| `src/services/providerCatalogStore.ts` | `/provider/*` |
| `src/services/listingsStore.ts` | `/listings/*` (bundled data used only if the API is down) |
| `src/services/platformApi.ts` | `/reviews/*`, `/conversations/*`, `/provider/staff/*`, `/admin/*`, `/search/`, `/trip-plans/` |

## Business rules

**Pricing.** The server prices every booking from `serviceType` + `serviceId`
(`"<listing id>:<facility id>"`). The facility is a provider catalog item (managed in the
dashboard) or a public facility (`listings.Facility`, editable in Django admin). Prices sent
by the browser are ignored. Rooms and vehicle hire are priced per night/day; everything else
per guest or item. A partial payment is a 30% deposit. Restaurant and transport base prices
are converted from RWF the same way the UI shows them.

**Availability** is checked when quoting and again inside the booking transaction:

- dates in the past or more than a year ahead are rejected;
- provider *blocked dates* and *closed time slots* are rejected;
- overnight stays: on each night, active bookings for that room or vehicle must be below its
  inventory (`totalCount`);
- appointments need a time slot; guests in a slot can't exceed its capacity (the catalog
  `capacity`, else a per-type default), and a day can't exceed the rule's `capacityPerDay`;
- shop orders reduce stock atomically, and cancelling returns it.

**Status transitions.** Anything not listed is rejected:

```
pending_payment → confirmed | cancelled
confirmed       → checked_in | cancelled | completed
checked_in      → checked_out | completed
checked_out     → completed
```

Guests may only cancel, check in (from the arrival date) and check out (only with nothing left
to pay). When a *provider* checks a guest out, completes or delivers, the remaining balance is
recorded as collected. Cancelling refunds what was paid (`amountRefunded`). Fulfillment steps
only move forward: shop orders go preparing → ready → out for delivery → delivered; services go
in service → fulfilled.

**Who sees what.** Tourists see bookings made while signed in. Providers see bookings for their
linked listing, plus their own trips. Admins see everything. A booking made as a guest with an
email is added to an account only after that account verifies the email.

**Deleting** a booking archives it: it's hidden from lists, can be restored, and is still
included in CSV exports with `archived=1`.

## API reference

Base URL: `/api`. Authenticated endpoints need `Authorization: Bearer <access>`.
Errors look like `{"message": "...", ...field errors}`; the frontend shows `message`.
List endpoints accept `?page=N&page_size=M` (max 200) and then return
`{count, page, pageSize, hasMore, results}`.

### Auth

| Method | Path | Body → Response |
|---|---|---|
| POST | `/auth/register/` | `{email, password, name, role}` → `{user, access}` + refresh cookie. Sends a verification email. `admin` can't be self-assigned |
| POST | `/auth/login/` | `{email, password}` → `{user, access}` + refresh cookie |
| POST | `/auth/refresh/` | (cookie) → `{user, access}`; rotates the cookie |
| POST | `/auth/logout/` | blacklists the refresh token, clears the cookie |
| GET / PATCH | `/auth/me/` | `User`; PATCH `{name?, avatar?, phone?}` |
| POST | `/auth/change-password/` | `{current_password, new_password}`; signs out other devices |
| POST | `/auth/password-reset/` | `{email}` → always 204 (emails a link if the account exists) |
| POST | `/auth/password-reset/confirm/` | `{uid, token, password}` |
| POST | `/auth/verify-email/` | `{uid, token}` → `{claimedBookings, user}` |
| POST | `/auth/resend-verification/` | (signed in) |

`User` = `{id, email, name, role, avatar, phone, emailVerified}`.

### Listings, search, trip plans (public)

| Method | Path | Notes |
|---|---|---|
| GET | `/listings/` | `{hotel: [...], park: [...], ...}`; `?type=hotel` returns a flat list |
| GET | `/listings/<type>/`, `/listings/<type>/<id>/` | filters `search`, `province`, `category`, `min_rating` |
| GET | `/listings/reference/` | `{spaTreatmentsCatalog, shopCategories}` |
| GET | `/search/` | `q`, `type` (comma list), `region`, `min_price`, `max_price`, `min_rating`, `sort` |
| POST | `/trip-plans/` | `{destination, startDate?, endDate?, duration?, budget?, travelers?, interests?, accommodation?, travelStyle?}` → itinerary with live prices; saved when signed in |
| GET | `/trip-plans/` | your saved plans |

### Bookings

| Method | Path | Notes |
|---|---|---|
| POST | `/bookings/quote/` | `{serviceType, serviceId, checkIn, checkOut?, timeSlot?, guests}` → price + `available` / `reason` |
| GET | `/availability/` | `service_type, service_id, from, to[, date]` → `{days: {date: free/limited/full}, slots?}` |
| GET / POST | `/bookings/` | GET filters: `service_type`, `status`, `from`, `to`, `search`, `mine=1`, `archived=1`. POST: guests allowed, rate-limited |
| GET / DELETE | `/bookings/<id>/` | DELETE archives (provider/admin) |
| POST | `/bookings/<id>/restore/` | un-archive |
| POST | `/bookings/<id>/status/` | `{status}` (see transitions) |
| POST | `/bookings/<id>/pay-balance/` | `{method?}` |
| POST | `/bookings/<id>/fulfillment/` | `{fulfillment}` (provider) |
| GET | `/bookings/stats/` | totals, by status / type / month / payment method, top items |
| GET | `/bookings/export.csv` | same filters as the list (provider/admin) |
| GET | `/bookings/lookup/?reference=&email=` | find a guest booking (rate-limited) |
| GET / POST | `/notifications/`, `/notifications/<id>/read/`, `/notifications/read-all/` | |

### Reviews and messages

| Method | Path | Notes |
|---|---|---|
| GET | `/reviews/?service_type=&listing_id=` | public reviews + summary |
| POST | `/reviews/` | `{bookingId, rating, title?, comment}`; only for your own checked-out or completed booking, once |
| GET | `/reviews/mine/`, `/reviews/provider/` | your reviews / reviews of your listing (with distribution) |
| POST | `/reviews/<id>/reply/` | provider of that listing |
| DELETE | `/reviews/<id>/` | author or admin (unpublishes) |
| GET / POST | `/conversations/` | list; start with `{bookingId}` or `{serviceType, listingId}` + `message` |
| GET / POST | `/conversations/<id>/messages/` | read (marks read) / send `{body}` |

### Provider workspace (provider roles only)

| Method | Path | Notes |
|---|---|---|
| GET | `/provider/workspace/` | created with a sample catalog on first access |
| PATCH | `/provider/workspace/profile/` | `linkedListingId` must not be managed by another provider |
| POST, PUT / DELETE | `/provider/catalog/`, `/provider/catalog/<id>/` | catalog items |
| PUT / DELETE | `/provider/availability/<id>/` | availability rules |
| GET / POST, PATCH / DELETE | `/provider/staff/`, `/provider/staff/<id>/` | team members |
| GET | `/provider/public-workspaces/` | public overrides for company pages |

### Uploads, admin, other

| Method | Path | Notes |
|---|---|---|
| POST | `/uploads/` | multipart `file` (JPG/PNG/WebP, max 5 MB) → `{url}`; re-encoded with metadata stripped |
| GET | `/admin/overview/` | admin only: users, bookings, listings, reviews, inquiries, providers |
| GET, PATCH | `/admin/users/`, `/admin/users/<id>/` | search/filter; `{isActive?, role?}` |
| GET, PATCH | `/admin/inquiries/`, `/admin/inquiries/<contact or demo>/<id>/` | `{handled}` |
| POST | `/contact/`, `/demo-requests/` | public forms (rate-limited; staff are emailed) |
| GET | `/health/`, `/meta/` | |

## Seed data

`seed_data/*.json` (listings, facilities with prices, demo bookings, provider samples) is
generated from the frontend's bundled data. After editing `src/data/*.ts`, regenerate and
reload:

```powershell
cd ..\tourista-rwanda-digital-oasis; npm run export:seed
cd ..\backend; python manage.py seed_demo
```

## Tests

Run `python manage.py test` for the backend (44 tests) and `npm test` in the frontend
(Vitest, 18 tests).

## Known limitations

- **No real payment gateway.** The server now computes every amount, but "paying" only
  records the payment, and refunds are recorded, not sent. Integrate MTN MoMo, Flutterwave or
  Stripe before taking real money.
- Uploaded images are stored on local disk (`media/`) and served by Django only while `DEBUG`
  is on. Use your web server or object storage in production.
- For production: set `DJANGO_DEBUG=false`, a real `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
  PostgreSQL and SMTP settings, and remove the demo-account shortcut from `LoginForm.tsx`.
#   T o u r i s t a - B a c k e n d  
 
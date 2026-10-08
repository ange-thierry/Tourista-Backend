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

Every endpoint is listed below with who may call it, what it expects and what it returns.

**Contents:** [Conventions](#conventions) · [System](#system) · [Auth](#auth) ·
[Listings](#listings) · [Search and trip planner](#search-and-trip-planner) ·
[Bookings](#bookings) · [Notifications](#notifications) · [Reviews](#reviews) ·
[Messages](#messages) · [Provider workspace](#provider-workspace) · [Uploads](#uploads) ·
[Contact and demo forms](#contact-and-demo-forms) · [Admin](#admin)

### Conventions

- **Base URL:** `http://127.0.0.1:8000/api`. All paths below are relative to it and end with `/`
  (except `bookings/export.csv`).
- **Format:** JSON in and out, with camelCase keys (query parameters are snake_case). Uploads use `multipart/form-data`.
- **Authentication:** send `Authorization: Bearer <access>`. The access token comes from
  login/register/refresh and lasts `JWT_ACCESS_MINUTES` (60). The refresh token lives in an
  httpOnly cookie `tourista_refresh` (path `/api/auth/`, `JWT_REFRESH_DAYS` = 7 days). Scripts that
  can't keep cookies may send `{"refresh": "..."}` in the body of `/auth/refresh/` and
  `/auth/logout/` instead.
- **Access column:** *Public* = no token needed; *Signed in* = any active account;
  *Provider* = one of the provider roles (everyone except `tourist` and `admin`);
  *Admin* = `role: admin` or a superuser.
- **Errors** are standard DRF errors plus a top-level `message` you can show to the user:

  ```json
  { "message": "checkIn: This date is in the past.", "checkIn": ["This date is in the past."] }
  ```

  Status codes: `400` validation, `401` missing/expired token, `403` not allowed,
  `404` not found, `429` rate-limited.
- **Pagination** (bookings, notifications, reviews, admin users): without `?page` you get a plain
  array. With `?page=N&page_size=M` (default 50, max 200) you get
  `{count, page, pageSize, hasMore, results}`.
- **Rate limits** (per IP / user, change in `.env`): auth endpoints 30/min, booking creation 30/h,
  booking lookup 20/h, contact & demo forms 20/h, uploads 60/h. Disabled while running tests.
- **Dates** are `YYYY-MM-DD`; timestamps are ISO 8601 UTC (`2026-10-08T09:30:00Z`); money is in
  USD as numbers.

Quick try from PowerShell:

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/auth/login/ `
  -ContentType 'application/json' -Body '{"email":"tourist@tourista.rw","password":"Tourista@2026"}'
Invoke-RestMethod http://127.0.0.1:8000/api/bookings/ -Headers @{ Authorization = "Bearer $($login.access)" }
```

### Shared objects

**User**

```json
{ "id": "3", "email": "tourist@tourista.rw", "name": "Demo Tourist", "role": "tourist",
  "avatar": "https://...", "phone": "+250...", "emailVerified": true }
```

**Booking** (returned by every booking endpoint; keys whose value is `null` are left out)

```json
{
  "id": "bk_1759911000000_AB12CD", "reference": "TR-20261008-4KQZ", "userId": "3",
  "serviceType": "hotel", "serviceId": "1:deluxe-room", "serviceName": "Serena Hotel · Deluxe Room",
  "location": "Kigali, Kigali City", "image": "https://...", "listingId": 1,
  "checkIn": "2026-10-20", "checkOut": "2026-10-23", "timeSlot": "10:00", "guests": 2,
  "unitPrice": 180.0,
  "guestInfo": { "fullName": "Jane Doe", "email": "jane@example.com", "phone": "+250...", "specialRequests": "..." },
  "payment": {
    "type": "partial", "method": "mobile_money", "status": "partial",
    "totalAmount": 540.0, "amountPaid": 162.0, "amountDue": 378.0, "amountRefunded": 0.0,
    "depositPercent": 30, "currency": "USD", "paidAt": "2026-10-08T09:30:00Z", "reference": "TR-20261008-9XYZ"
  },
  "status": "confirmed", "fulfillment": "not_started",
  "createdAt": "...", "updatedAt": "...", "checkedInAt": "...", "checkedOutAt": "...",
  "notes": "...", "isArchived": true, "archivedAt": "..."
}
```

Enumerations (also available from `GET /meta/`):

| Name | Values |
|---|---|
| `role` | `tourist`, `hotel_owner`, `tour_operator`, `restaurant_owner`, `transport_owner`, `park_manager`, `destination_manager`, `history_culture_manager`, `artisan`, `shop_owner`, `spa_manager`, `admin` |
| `serviceType` | `hotel`, `destination`, `park`, `restaurant`, `transport`, `spa`, `artisan`, `history-culture`, `shop` |
| `status` | `pending_payment`, `confirmed`, `checked_in`, `checked_out`, `cancelled`, `completed` |
| `fulfillment` | `not_started`, `preparing`, `ready`, `out_for_delivery`, `delivered`, `in_service`, `fulfilled` |
| `paymentType` | `full`, `partial` (30% deposit) |
| `paymentMethod` | `card`, `mobile_money`, `bank_transfer` |
| `payment.status` | `unpaid`, `partial`, `paid`, `refunded` |
| notification `type` | `booking`, `payment`, `checkin`, `checkout`, `reminder`, `system` |

---

### System

#### `GET /health/` — Public
Liveness check. → `{"status": "ok", "time": "<ISO timestamp>"}`

#### `GET /meta/` — Public
All enumerations as `{value, label}` lists, for dropdowns and labels:
`{roles, providerRoles, roleServiceTypes, serviceTypes, bookingStatuses, fulfillmentStatuses, paymentMethods}`.
`roleServiceTypes` maps each provider role to the booking types its dashboard manages
(e.g. `"hotel_owner": ["hotel"]`).

---

### Auth

All under `/auth/`. Login, register, refresh and the reset/verify endpoints are rate-limited (30/min).

#### `POST /auth/register/` — Public
Create an account and sign in.

| Field | Required | Notes |
|---|---|---|
| `email` | yes | unique (case-insensitive), stored lowercase |
| `password` | yes | must pass Django's password validators (length, not too common, not all numeric…) |
| `name` | yes | max 150 chars |
| `role` | no | default `tourist`; any role except `admin` |

→ `201 {user, access}` and sets the refresh cookie. A verification email is sent (printed in the
terminal in development). Errors: `400` email taken, weak password, or `admin` role.

#### `POST /auth/login/` — Public
Body `{email, password}` → `200 {user, access}` + refresh cookie.
`400 "Invalid email or password."` or `"This account is disabled."`.

#### `POST /auth/refresh/` — Public (needs the cookie)
Exchanges the refresh cookie (or body `refresh`) for a new access token. The old refresh token is
blacklisted and a new cookie is set (rotation). → `200 {user, access}`.
`401` if there is no cookie or it is expired/revoked (the cookie is then cleared). The frontend calls
this on page load to restore the session and whenever a request gets `401`.

#### `POST /auth/logout/` — Public
Blacklists the refresh token and clears the cookie. Always → `204`.

#### `GET /auth/me/` — Signed in
→ the current `User`.

#### `PATCH /auth/me/` — Signed in
Update your profile. Any of `{name, avatar, phone}` (`avatar` is a URL, usually from `/uploads/`).
Email and role can't be changed here. → the updated `User`.

#### `POST /auth/change-password/` — Signed in
Body `{current_password, new_password}`. Every other session is signed out (all refresh tokens
blacklisted); this one gets a fresh `{user, access}` + cookie.
`400` if the current password is wrong or the new one is weak.

#### `POST /auth/password-reset/` — Public
Body `{email}`. If an active account exists, emails a link to
`<FRONTEND_URL>/reset-password?uid=...&token=...`. Always → `204`, so it can't be used to find out
which emails are registered.

#### `POST /auth/password-reset/confirm/` — Public
Body `{uid, token, password}` (the `uid` and `token` come from the emailed link).
Sets the new password, marks the email as verified, signs out all sessions and attaches any guest
bookings made with that email. → `{"message": "Password updated. You can now sign in."}`.
`400 "This link is invalid or has expired."`

#### `POST /auth/verify-email/` — Public
Body `{uid, token}` from the link `<FRONTEND_URL>/verify-email?uid=...&token=...`.
Marks the email verified and attaches bookings that were made as a guest with this email.
→ `{message, claimedBookings: <number>, user}`. A link only works once.

#### `POST /auth/resend-verification/` — Signed in
Sends a new verification link. → `{message}` (also when already verified).

---

### Listings

Public catalog data (hotels, parks, restaurants…). A listing is identified by
`serviceType` + numeric `id`. The response is the listing's full JSON from `seed_data/listings.json`
plus `{id, name, location, province, image, rating, reviews, category, description}`.

#### `GET /listings/` — Public
All published listings grouped by type: `{"hotel": [...], "park": [...], ...}`.
With `?type=hotel` → a flat array of that type.

Filters (also on the next endpoint):

| Param | Matches |
|---|---|
| `search` | text in name, location, description or category |
| `province` | exact province (case-insensitive), e.g. `Northern Province` |
| `category` | exact category (case-insensitive) |
| `min_rating` | rating ≥ value |

#### `GET /listings/<type>/` — Public
Array of listings of one type, e.g. `/listings/hotel/?province=Kigali City`. `404` for an unknown type.

#### `GET /listings/<type>/<id>/` — Public
One listing, e.g. `/listings/park/2/`. `404` if missing or unpublished.

#### `GET /listings/reference/` — Public
Static reference data: `{spaTreatmentsCatalog: [...], shopCategories: [...]}`.

---

### Search and trip planner

#### `GET /search/` — Public
Searches across all listing types.

| Param | Notes |
|---|---|
| `q` | words; every word must appear in name, location, province, description or category |
| `type` | comma list of service types, or `all` |
| `region` | `kigali`, `northern`, `southern`, `eastern`, `western` |
| `min_price`, `max_price` | USD; listings without a price are dropped when set |
| `min_rating` | number |
| `sort` | `relevance` (default: name matches first, then rating), `rating`, `price-low`, `price-high`, `name` |

→ `{count, results}` (max 200). Each result:
`{id: "park-2", listingId, type, name, description, category, location, province, region, image,
rating, reviews, price: "$1,500 per person", priceValue, url: "/parks/2", details: {amenities,
highlights, contact: {phone, website}, availability, duration}}`.

#### `POST /trip-plans/` — Public (saved only when signed in)
Builds a day-by-day itinerary from real listings and live prices. All fields optional:

| Field | Example | Notes |
|---|---|---|
| `destination` | `"Musanze"` | a place or listing name; picks the region |
| `startDate`, `endDate` | `"2026-11-01"` | used for the length if both are set |
| `duration` | `"5 days"`, `"1 week"` | otherwise; default 3, max 14 days |
| `budget` | `"$2000"` | total USD; the first number is used |
| `travelers` | `"2"` | rooms = travelers ÷ 2, rounded up |
| `interests` | `"wildlife, culture"` | `wildlife`, `nature`, `culture`, `food`, `relax`, `shopping`, `adventure` |
| `accommodation`, `travelStyle` | `"luxury"`, `"budget"` | choose the most/least expensive hotel |

→ `201 {id?, destination, region, duration, days, travelers, budget, estimatedTotal, withinBudget,
highlights, dailyItinerary: [{day, activities, recommendations}], travelTips,
budgetBreakdown: [{category, amount, description}], suggestions: [{role, type, listingId, name, url,
price, priceLabel}], generatedAt}`. `id` is present only when the plan was saved.

#### `GET /trip-plans/` — Signed in
Your last 20 saved plans: `[{id, createdAt, ...plan}]`.

---

### Bookings

**What is being booked** is always `serviceType` + `serviceId`, where `serviceId` is
`"<listing id>"` or `"<listing id>:<option id>"` (a provider catalog item or a public facility, e.g.
`"1:deluxe-room"`, `"3:hot-stone"`). The server works out the price, inventory and schedule from it.
Each option has one of three schedules:

| Schedule | Used by | Dates | Time slot | `guests` means | Priced |
|---|---|---|---|---|---|
| `overnight` | hotel rooms, vehicle hire | `checkIn` → `checkOut` | no | people | per night/day |
| `day_visit` | parks, tours, spa, restaurants, culture, artisans | `checkIn` only | **required** (`"10:00"` or `"10:00 - 11:00"`) | people | per guest |
| `order` | shop products | `checkIn` (delivery date) | optional window | quantity | per item |

#### `POST /bookings/quote/` — Public
Price and availability before paying. Nothing is saved.

```json
{ "serviceType": "spa", "serviceId": "1:hot-stone", "checkIn": "2026-10-20", "timeSlot": "10:00", "guests": 2 }
```

`checkOut` is optional (defaults to `checkIn`). →

```json
{ "serviceName": "...", "location": "...", "image": "...", "schedule": "day_visit", "maxGuests": null, "stock": null,
  "unitPrice": 60.0, "pricingMode": "per_guest", "units": 2, "nights": 0, "totalAmount": 120.0,
  "depositPercent": 30, "depositAmount": 36.0, "currency": "USD",
  "available": false, "reason": "Only 1 place left at 10:00." }
```

When `available` is false, `reason` says why (past date, more than a year ahead, blocked day, slot
full or closed, no slot chosen, too many guests, out of stock, check-out not after check-in).

#### `GET /availability/` — Public
Calendar data for one option.

| Param | Notes |
|---|---|
| `service_type`, `service_id` | required, as above |
| `from`, `to` | date range; defaults today → +90 days, capped at one year |
| `date` | optional; also returns that day's time slots |

→ `{serviceName, schedule, pricingMode, unitPrice, inventory, slotCapacity, stock,
days: {"2026-10-20": "free" | "limited" | "full", ...}, slots?: [{time, endTime, status, remaining, note}]}`.
Slot `status` is `free`, `limited`, `full` or `closed` (closed by the provider, or the time has passed).

#### `POST /bookings/` — Public (guests allowed, 30/hour)
Create a booking. Same fields as the quote, plus guest and payment details:

```json
{
  "serviceType": "hotel", "serviceId": "1:deluxe-room",
  "checkIn": "2026-10-20", "checkOut": "2026-10-23", "guests": 2,
  "guestInfo": { "fullName": "Jane Doe", "email": "jane@example.com", "phone": "+250788000000", "specialRequests": "Late arrival" },
  "paymentType": "partial", "paymentMethod": "mobile_money"
}
```

- Availability is checked again inside a database lock, so two people can't take the last room.
- `full` records the whole amount as paid; `partial` records a 30% deposit. Either way the booking
  starts as `confirmed` (`pending_payment` only for a free booking with nothing paid).
- Shop orders reduce stock. Shop, spa, restaurant and artisan bookings get `fulfillment: "not_started"`.
- Signed-in users own the booking (send the Bearer token). Guests can find it later with
  `/bookings/lookup/`, and it moves into their account once they verify that email.
- The booker gets "Booking confirmed" and "Payment received" notifications, the provider gets
  "New booking received", and both get an email.
- Price fields sent by the client (`unitPrice`, `totalAmount`, …) are ignored.

→ `201` Booking. `400` with a field message when it can't be booked.

#### `GET /bookings/` — Signed in
Bookings you can see: tourists see their own; providers see bookings for their linked listing plus
their own trips; admins see all. Archived bookings are hidden unless `archived=1`.

| Param | Notes |
|---|---|
| `service_type` | comma list |
| `status` | comma list |
| `from`, `to` | bookings overlapping this date range |
| `search` | reference, guest name, guest email or service name |
| `mine=1` | only bookings you made yourself (useful for providers) |
| `archived=1` | only archived bookings |
| `page`, `page_size` | see Pagination |

#### `GET /bookings/<id>/` — Signed in (owner, provider of the listing, or admin)
One Booking. `403` if it isn't yours, `404` if it doesn't exist.

#### `DELETE /bookings/<id>/` — Provider of the listing or admin
Archives (soft-deletes) the booking. It disappears from lists but stays in the database and in
`export.csv?archived=1`. → `204`.

#### `POST /bookings/<id>/restore/` — Provider of the listing or admin
Un-archives a booking. → Booking.

#### `POST /bookings/<id>/status/` — Owner, provider or admin
Body `{"status": "checked_in"}`. Allowed moves:

```
pending_payment → confirmed | cancelled
confirmed       → checked_in | cancelled | completed
checked_in      → checked_out | completed
checked_out     → completed
```

- Guests may cancel, check in (from the arrival date) and check out (only once nothing is owed).
  Only the provider/admin can `confirm` or `complete`.
- When a provider checks out or completes, the remaining balance is recorded as collected.
- `cancelled` refunds what was paid (`amountRefunded`, payment status `refunded`) and returns shop stock.
- Archived bookings can't change. → updated Booking; `400` for a move that isn't allowed.

#### `POST /bookings/<id>/pay-balance/` — Owner, provider or admin
Body `{"method": "card"}` (optional). Records the remaining balance as paid; a `pending_payment`
booking becomes `confirmed`. Not allowed for cancelled, completed or archived bookings. → Booking.
(No real payment provider is called yet; see Known limitations.)

#### `POST /bookings/<id>/fulfillment/` — Provider of the listing or admin
Body `{"fulfillment": "preparing"}`. Moves an order/service along its track; steps only go forward:

- shop: `not_started → preparing → ready → out_for_delivery → delivered`
- spa, restaurant, artisan: `not_started → in_service → fulfilled`

`out_for_delivery` / `in_service` also set the status to `checked_in`; `delivered` / `fulfilled`
complete the booking and record the balance as collected. A `pending_payment` booking must be paid
or confirmed first. The guest gets an "Order update" notification. → Booking.

#### `GET /bookings/lookup/?reference=TR-...&email=...` — Public (20/hour)
Lets a guest without an account find their booking. Both must match. → Booking or `404`.

#### `GET /bookings/stats/` — Signed in
Dashboard numbers over the bookings you manage (providers: your listing; add `mine=1` for your own
trips instead), or your own bookings (tourists), or everything (admins). Accepts the same filters as
the list. →

```json
{ "bookings": 42, "revenue": 12500.0, "due": 800.0, "refunded": 150.0,
  "byStatus": {"pending_payment": 0, "confirmed": 10, ...},
  "byServiceType": {"hotel": 42},
  "byMonth": [{"month": "2026-10", "bookings": 12, "revenue": 3400.0}],
  "byPaymentMethod": {"card": 9000.0, "mobile_money": 3500.0},
  "topOptions": [{"name": "Serena Hotel · Deluxe Room", "bookings": 8, "revenue": 4320.0}] }
```

#### `GET /bookings/export.csv` — Provider or admin
Downloads a CSV (`bookings-YYYY-MM-DD.csv`) of the same bookings as the list, with the same filters
(`archived=1` includes archived ones). Columns: reference, service, type, guest, email, phone, dates,
time, guests, status, fulfillment, payment status, method, total, paid, due, refunded, created, archived.

#### `GET /bookings/occupancy/` — Public (legacy)
Anonymised active bookings (no guest details) for `?service_type=&listing_id=`, max 1000. Kept for
older calendars; new code should use `/availability/`.

---

### Notifications

In-app notifications for the signed-in user (booking confirmations, payments, check-in/out,
cancellations, new messages, review replies…).

#### `GET /notifications/` — Signed in
Newest first, last 100 (or paginate with `page`). `?unread=1` for unread only.
Each: `{id, userId, title, message, type, read, createdAt, bookingId?}`.

#### `POST /notifications/<id>/read/` — Signed in
Marks one as read. → `204`, or `404` if it isn't yours.

#### `POST /notifications/read-all/` — Signed in
Marks all as read. → `204`.

---

### Reviews

Only guests who actually stayed or visited can review: the booking must be theirs and be
`checked_out` or `completed`, one review per booking. A listing's rating blends its original catalog
rating with published guest reviews.

Review object: `{id, serviceType, listingId, bookingId, serviceName, rating, title, comment,
authorName: "Jane D.", reply, repliedAt, createdAt}`.

#### `GET /reviews/?service_type=hotel&listing_id=1` — Public
Published reviews for a listing (both params required; supports pagination). →
`{results, summary: {guestReviews, guestAverage, rating, reviews}}` (plus pagination keys when paged).

#### `POST /reviews/` — Signed in
Body `{bookingId, rating: 1–5, title?, comment}` (title ≤ 120, comment ≤ 3000 chars).
Updates the listing rating and notifies the provider. → `201` Review.
`400` if the booking isn't finished or was already reviewed; `403` if it isn't yours.

#### `GET /reviews/mine/` — Signed in
All reviews you wrote.

#### `GET /reviews/provider/` — Provider
Reviews of your linked listing (max 200) with
`summary: {guestReviews, guestAverage, unanswered, distribution: {"1": n, …, "5": n}, rating, reviews}`.

#### `POST /reviews/<id>/reply/` — Provider of that listing or admin
Body `{reply}` (≤ 3000 chars). Replaces any earlier reply and notifies the reviewer. → Review.

#### `DELETE /reviews/<id>/` — Author or admin
Unpublishes the review and recalculates the listing rating. → `204`.

---

### Messages

Guest ↔ provider conversations. A conversation belongs to one guest and one provider workspace,
optionally tied to a booking. Each new message notifies the other side.

#### `GET /conversations/` — Signed in
Your conversations (as guest or as provider; admins see all), max 200. Each:
`{id, subject, role: "guest" | "provider", companyName, serviceType, listingId, guestName,
guestEmail (provider side only), bookingId, bookingReference, lastMessage, lastMessageAt, unread}`.

#### `POST /conversations/` — Signed in
Start a conversation (or add to the existing one with the same company and booking):

```json
{ "bookingId": "bk_...", "message": "Can I check in early?" }
{ "serviceType": "hotel", "listingId": 1, "subject": "Group rates", "message": "Hello..." }
```

Give either `bookingId` (must be your booking) or `serviceType` + `listingId`. `subject` is optional.
→ `201` conversation. `400` if no provider manages that listing yet, or you manage it yourself.

#### `GET /conversations/<id>/messages/` — Participant or admin
→ `{conversation, messages: [{id, body, senderName, mine, createdAt}]}`. Marks the conversation read
for you.

#### `POST /conversations/<id>/messages/` — Participant or admin
Body `{body}` (≤ 4000 chars). → `201 {id, body, senderName, mine, createdAt}`.

---

### Provider workspace

For provider accounts only (`403` for tourists and admins). Each provider has one workspace: a company
profile linked to a public listing, a catalog of bookable items, availability rules and staff. It is
created with sample data the first time it's accessed. Every catalog/availability/profile call
returns the **whole workspace**:

```json
{ "userId": "2", "role": "hotel_owner", "serviceType": "hotel",
  "profile": {"companyName", "description", "location", "province", "hours", "phone", "amenities", "image", "linkedListingId"},
  "catalog": [CatalogItem], "availability": [AvailabilityRule], "updatedAt": "..." }
```

#### `GET /provider/workspace/` — Provider
Your workspace.

#### `PATCH /provider/workspace/profile/` — Provider
Any of `{companyName, description, location, province, hours, phone, amenities: [], image, linkedListingId}`.
`linkedListingId` is the public listing you manage; bookings and reviews for it show up in your
dashboard. `400` if another provider already manages that listing. → workspace.

#### `POST /provider/catalog/` — Provider
Add a catalog item (id generated by the server). → `201` workspace.

| Field | Notes |
|---|---|
| `name` | required |
| `price` | required, USD, ≥ 0 |
| `description`, `category`, `priceLabel`, `image` | optional text |
| `status` | `active` (bookable and shown publicly), `draft` (default), `paused` |
| `scheduleMode` | `overnight`, `day_visit` (default), `order` |
| `durationMinutes` | for appointments |
| `capacity` | guests per time slot (day visits) or max guests (overnight) |
| `stock` | items left (shop) |
| `availableCount`, `totalCount` | units, e.g. number of identical rooms |
| `amenities`, `beds`, `sizeSqm` | room details |

#### `PUT /provider/catalog/<itemId>/` — Provider
Creates or replaces the item with that id (same body). `400` if the id belongs to another provider.
→ workspace.

#### `DELETE /provider/catalog/<itemId>/` — Provider
Removes the item and its availability rules. → workspace.

#### `PUT /provider/availability/<ruleId>/` — Provider
Creates or replaces an availability rule:

| Field | Notes |
|---|---|
| `itemId` | catalog item id, or `all` (default) for every item |
| `blockedDates` | `["2026-12-25"]`: closed, can't be booked |
| `limitedDates` | shown as "limited" on calendars |
| `openTimeSlots` | `["09:00", "11:00"]`; default is every hour 08:00–19:00 |
| `closedTimeSlots` | slots that can't be booked |
| `capacityPerDay` | max bookings per day (default 4; `0` = no limit) |
| `notes` | text |

→ workspace. A rule for a specific item wins over the `all` rule.

#### `DELETE /provider/availability/<ruleId>/` — Provider
Removes the rule. → workspace.

#### `GET /provider/staff/` — Provider
Your team: `[{id, name, position, department, email, phone, shift, status, hiredOn, notes, createdAt}]`.
`status` is `active`, `on_leave` or `inactive`.

#### `POST /provider/staff/` — Provider
Add a staff member (same fields; `name` and `position` required). → `201` staff member.

#### `PATCH /provider/staff/<id>/` — Provider
Update any fields. → staff member.

#### `DELETE /provider/staff/<id>/` — Provider
→ `204`.

#### `GET /provider/public-workspaces/` — Public
What public company pages show: workspaces of active providers with only `active` catalog items.
Filter with `?service_type=hotel&listing_id=1`. → array of workspaces.

---

### Uploads

#### `POST /uploads/` — Signed in (60/hour)
`multipart/form-data` with a `file` field. JPG, PNG or WebP, max 5 MB (`UPLOAD_MAX_MB`).
The image is checked, resized to at most 2400 px and re-saved without metadata (EXIF/GPS).
→ `201 {url, width, height}`. Use `url` for avatars, company photos and catalog images.

```powershell
curl.exe -H "Authorization: Bearer <access>" -F "file=@photo.jpg" http://127.0.0.1:8000/api/uploads/
```

---

### Contact and demo forms

Public, 20/hour. Each submission is saved and emailed to staff (`STAFF_NOTIFICATION_EMAILS`, or all
admin accounts). → `201 {id, message: "Received. Our team will be in touch within 24 hours."}`.

#### `POST /contact/` — Public
`{name, email, subject?, message}`.

#### `POST /demo-requests/` — Public
`{fullName, email, preferredDate: "YYYY-MM-DD", preferredTime}` required; optional `phone, company,
stakeholderType, businessSize, attendees, specificNeeds, currentChallenges, goals, additionalInfo`.

---

### Admin

Powers the in-app admin dashboard. Admin only (`403` for everyone else). The full Django admin is
also at `/admin/` (not under `/api`).

#### `GET /admin/overview/` — Admin
→ `{users: {total, byRole, verified, newThisMonth}, bookings: <same shape as /bookings/stats/>,
listings: {<type>: count}, reviews: {count, average}, inquiries: {openContacts, openDemos},
recentBookings: [8 Bookings], providers: [{companyName, email, role, serviceType, listingId,
bookings, catalogItems}]}`.

#### `GET /admin/users/` — Admin
All users, newest first. `?role=` and `?search=` (email or name); supports pagination.
Each is a `User` plus `{isActive, dateJoined, lastLogin}`.

#### `PATCH /admin/users/<id>/` — Admin
Body `{isActive?, role?}` to disable/enable an account or change its role. You can't change your own
account. → User + `isActive`.

#### `GET /admin/inquiries/` — Admin
Contact messages and demo requests together, newest first (up to 100 of each). `?open=1` for
unhandled only. Each has `kind: "contact" | "demo"`, `name, email, subject, message, handled, createdAt`
(demo requests also `phone, company, preferredDate, preferredTime`).

#### `PATCH /admin/inquiries/<kind>/<id>/` — Admin
`kind` is `contact` or `demo`. Body `{handled: true | false}` (default `true`). → the inquiry.

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

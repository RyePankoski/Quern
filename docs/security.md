# Quern — Security Checklist

This document outlines the security requirements for Quern if the project proceeds to
production. These are not optional polish items — they are baseline requirements for a
financial application handling real contracts and real money.

---

## 1. Know who is doing things

Every action must be tied to a real, identified person.

- No shared logins
- Every user has their own credentials
- Every API call, form submission, and data change is attributed to a specific user
- "Who did this?" must always be answerable

**Implementation:** Flask-Login, user table in SQLite, session management.

---

## 2. Control what they are allowed to do

Not everyone should be able to do everything. Permissions must be enforced in the
backend — the UI hiding a button is not sufficient.

- Define roles (e.g. broker, accountant, admin)
- Restrict actions by role at the route level
- A broker should not be able to approve their own contract
- An accountant should not be able to delete contracts

**Implementation:** Role column on user model, decorator-based route guards.

---

## 3. Record what happened

Every change to a contract must leave a permanent, tamper-evident trail.

- Who made the change
- What field changed (old value → new value)
- When it happened
- What the contract state was before and after

**Implementation:** Audit log table in SQLite, written on every Books API PUT/POST.

---

## 4. Never lie to the user

The UI must always reflect reality as confirmed by Zoho Books.

- If a save fails, show the failure — never pretend it succeeded
- If data shown is not yet confirmed by Books, make that visible
- The contracts list must only show contracts that exist in Books
- Stale or unconfirmed data must be clearly marked

**Implementation:** Check Books API response codes before redirecting. Show error
messages on failure. Never optimistically update the UI before confirmation.

---

## 5. Prevent accidental overwrites

Two people editing the same contract simultaneously is dangerous. Last write must
not silently win.

- Capture the contract's last-modified timestamp when loading the edit form
- Send that timestamp with every update
- Reject the update if the contract has been modified since it was loaded
- Show the user a clear conflict warning and force a refresh

**Implementation:** Optimistic locking using `last_modified_time` from Books API
response. Display conflict resolution UI on mismatch.

---

## 6. Validate before sending

Bad data must never reach Zoho Books. The app should be stricter than a spreadsheet.

- Required fields must be enforced (buyer, seller, commodity, date at minimum)
- Logical consistency checks (buyer and seller cannot be the same entity)
- Numeric fields must be valid numbers within reasonable ranges
- Dates must be valid and logically ordered
- Validation must happen server-side — client-side validation alone is not sufficient

**Implementation:** Server-side validation in the route before calling the Books API.
Return descriptive error messages to the user on failure.

---

## 7. Treat every action like it matters

This is an internal tool, but it handles real contracts and real money. Every action
should be treated as if it could have financial consequences.

- No silent shortcuts
- No hidden behavior
- No "it probably worked" assumptions
- If something fails, say so clearly
- If something is irreversible, confirm before proceeding

---

## Implementation Priority

These items are blocked on auth and should be implemented together, not piecemeal:

1. Auth layer (Flask-Login, user table, sessions)
2. Role-based permissions (backend enforced)
3. Audit log
4. Form validation (can be done earlier, independent of auth)
5. Optimistic locking / conflict detection
6. UI truthfulness (submission confirmation, stale data indicators)
-- The restore drill's own data. DEVELOPMENT ONLY. NEVER RUN THIS AGAINST A DEPLOYED DATABASE.
--
-- WHY IT EXISTS. `just restore-drill` refuses to report a pass over an empty database, because a
-- restore of an empty table always succeeds: an instrument that cannot fail proves nothing, and a
-- drill whose evidence tables were empty is the most convincing false pass this ticket has. On the
-- deployed host the drill runs against real data and this file is not involved at all. In development
-- there is no data, so `just drill-local` seeds this first.
--
-- WHAT IT IS AND IS NOT. These are hand-written rows, not rows the product's own write paths
-- produced. The binding objects carry the four keys `stored_binding` writes and the occurrence key
-- the one derivation of it produces, so the rotation cursor derives through the real domain code; if
-- any of that were wrong, the fingerprint would report zero advanced cursors and the drill would
-- refuse rather than pass. That refusal is the check on this file.
--
-- WHAT THE DRILL NEEDS FROM IT. Rows in the five evidence tables, and one rotation habit with a
-- CONFIRMED COMPLETION, so the cursor sits somewhere other than its first variant and re-deriving it
-- after a restore is a real comparison rather than a comparison of two zeroes.
--
-- Idempotent: every insert is `ON CONFLICT DO NOTHING` against a fixed identifier, so running it
-- twice changes nothing and a drill can be repeated.

BEGIN;

INSERT INTO tenants (id, created_at)
VALUES ('11111111-1111-4111-8111-111111111111', now())
ON CONFLICT (id) DO NOTHING;

-- The password hash is a literal marker rather than a real one. Nothing signs in during a drill, and
-- a hash that could be verified would be a credential in the repository.
INSERT INTO users (id, tenant_id, email, password_hash, created_at)
VALUES (
    '22222222-2222-4222-8222-222222222222',
    '11111111-1111-4111-8111-111111111111',
    'drill@localhost',
    'not-a-real-hash-nothing-signs-in-during-a-drill',
    now()
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO areas (id, parent_id, name, pigment_index, budget_percent, floor_hours, created_at, tenant_id)
VALUES (
    '33333333-3333-4333-8333-333333333333',
    NULL,
    'Training',
    3,
    10.00,
    NULL,
    now(),
    '11111111-1111-4111-8111-111111111111'
)
ON CONFLICT (id) DO NOTHING;

-- A ROTATION habit with four variants. The cursor is the count of confirmed completions modulo four,
-- so the single confirmed row below puts it on the second variant: index 1, `Back`.
INSERT INTO habits (
    id, area_id, title, cadence_kind, cadence_times_per_week, cadence_approx_days,
    duration_min_minutes, duration_max_minutes, miss_policy, binding_source, variants,
    debt_cap_periods, created_at, tenant_id
)
VALUES (
    '44444444-4444-4444-8444-444444444444',
    '33333333-3333-4333-8333-333333333333',
    'Gym',
    'times_per_week',
    4,
    NULL,
    60,
    90,
    'debt',
    'rotation',
    '["Chest", "Back", "Legs", "Shoulders"]'::jsonb,
    2,
    now(),
    '11111111-1111-4111-8111-111111111111'
)
ON CONFLICT (id) DO NOTHING;

-- The plan history. One revision, because the outcome rows reference one.
INSERT INTO plan_revisions (
    id, tenant_id, iso_week, status, reason, document, objective_breakdown,
    weight_set_version, input_version, supersedes_id, created_at, approved_at
)
VALUES (
    '55555555-5555-4555-8555-555555555555',
    '11111111-1111-4111-8111-111111111111',
    '2026-W32',
    'applied',
    'materialized',
    '{"blocks": [], "note": "seeded for the restore drill"}'::jsonb,
    '{"total": 0.0}'::jsonb,
    1,
    1,
    NULL,
    now(),
    NULL
)
ON CONFLICT (id) DO NOTHING;

-- TWO OUTCOMES, one confirmed complete and one confirmed skipped. The skipped row is what makes the
-- cursor's arithmetic visible: a skip does not advance it, so a restore that lost the COMPLETED row
-- and kept the skipped one would come back with the same row count and a different cursor.
INSERT INTO block_outcomes (
    id, tenant_id, block_id, binding, revision_id, state, actual_minutes,
    actual_starts_at, actual_ends_at, occurred_at, confirmed_at
)
VALUES
    (
        '66666666-6666-4666-8666-666666666661',
        '11111111-1111-4111-8111-111111111111',
        'drill-block-00',
        '{"kind": "habit", "entity_id": "44444444-4444-4444-8444-444444444444", "occurrence_key": "00", "split_index": null}'::jsonb,
        '55555555-5555-4555-8555-555555555555',
        'completed',
        NULL,
        NULL,
        NULL,
        now() - interval '3 days',
        now() - interval '3 days'
    ),
    (
        '66666666-6666-4666-8666-666666666662',
        '11111111-1111-4111-8111-111111111111',
        'drill-block-01',
        '{"kind": "habit", "entity_id": "44444444-4444-4444-8444-444444444444", "occurrence_key": "01", "split_index": null}'::jsonb,
        '55555555-5555-4555-8555-555555555555',
        'skipped',
        NULL,
        NULL,
        NULL,
        now() - interval '2 days',
        now() - interval '2 days'
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO pins (
    id, tenant_id, iso_week, binding, starts_at, ends_at, superseded_starts_at,
    superseded_ends_at, objective_delta, weight_set_version, created_at, block_id
)
VALUES (
    '77777777-7777-4777-8777-777777777777',
    '11111111-1111-4111-8111-111111111111',
    '2026-W32',
    '{"kind": "habit", "entity_id": "44444444-4444-4444-8444-444444444444", "occurrence_key": "02", "split_index": null}'::jsonb,
    now(),
    now() + interval '1 hour',
    now() + interval '2 hours',
    now() + interval '3 hours',
    NULL,
    1,
    now(),
    'drill-block-02'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO week_adjustments (
    id, tenant_id, iso_week, kind, target_id, reductions, delta_minutes, created_at,
    created_by_operation_id
)
VALUES (
    '88888888-8888-4888-8888-888888888888',
    '11111111-1111-4111-8111-111111111111',
    '2026-W32',
    'reduce_routine',
    '44444444-4444-4444-8444-444444444444',
    '{"2026-08-05": 30}'::jsonb,
    -30,
    now(),
    '99999999-9999-4999-8999-999999999999'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO edit_events (
    id, tenant_id, iso_week, binding, proposed_starts_at, proposed_ends_at,
    accepted_starts_at, accepted_ends_at, objective_delta, context, weight_set_version, created_at
)
VALUES (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    '11111111-1111-4111-8111-111111111111',
    '2026-W32',
    '{"kind": "habit", "entity_id": "44444444-4444-4444-8444-444444444444", "occurrence_key": "02", "split_index": null}'::jsonb,
    now(),
    now() + interval '1 hour',
    now() + interval '2 hours',
    now() + interval '3 hours',
    0.25,
    '{"note": "seeded for the restore drill"}'::jsonb,
    1,
    now()
)
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- 007_triggers.sql
-- Auto-creates a rag.user_profiles row whenever a new user
-- signs up via Supabase Auth.
-- ============================================================


-- ============================================================
-- STEP 1 — Create the trigger function
-- This is the code that runs when the trigger fires.
-- ============================================================

CREATE OR REPLACE FUNCTION rag.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
-- CONCEPT: SECURITY DEFINER means this function runs as the
-- superuser who created it, not as the user triggering it.
-- This is necessary because new users don't have permission
-- to insert into rag.user_profiles at the moment of signup —
-- they don't even have a session yet. SECURITY DEFINER lets
-- the function act on their behalf with elevated privileges
-- for this one specific insert.
SECURITY DEFINER
AS $$
BEGIN
    -- CONCEPT: NEW is a special variable available inside trigger
    -- functions. It refers to the row that was just inserted —
    -- in this case the new row in auth.users.
    -- NEW.id is the UUID Supabase Auth assigned to this user.
    -- NEW.raw_user_meta_data is a JSONB column where Supabase
    -- stores extra signup fields. If your frontend passes a
    -- display_name during signup, it lands here.

    INSERT INTO rag.user_profiles (id, display_name)
    VALUES (
        NEW.id,
        NEW.raw_user_meta_data->>'full_name'
        -- CONCEPT: ->>' extracts a text value from JSONB.
        -- If full_name wasn't passed during signup, this returns
        -- NULL — which is fine, display_name is nullable.
        -- You can update it later from the profile settings page.
    );

    -- CONCEPT: RETURN NEW is required for AFTER INSERT triggers
    -- on row-level operations. It tells PostgreSQL the trigger
    -- completed successfully. Returning NULL would signal failure.
    RETURN NEW;
END;
$$;


-- ============================================================
-- STEP 2 — Attach the trigger to auth.users
-- ============================================================

CREATE OR REPLACE TRIGGER on_auth_user_created
    -- CONCEPT: AFTER INSERT means the trigger fires after the new
    -- auth.users row is successfully committed — not before.
    -- Using BEFORE INSERT would risk creating a profile for a
    -- signup that subsequently fails. AFTER is always safer here.
    AFTER INSERT ON auth.users
    -- FOR EACH ROW means run once per inserted row.
    -- The alternative is FOR EACH STATEMENT which runs once
    -- per INSERT statement regardless of how many rows it affects.
    -- Always use FOR EACH ROW for signup triggers.
    FOR EACH ROW
    EXECUTE FUNCTION rag.handle_new_user();
-- revision = '0007'
-- down_revision = '0006'
--
-- Existing users have no credential and cannot log in until provisioned.
ALTER TABLE claimguard.users ADD COLUMN password_hash TEXT;

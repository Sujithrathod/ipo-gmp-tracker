-- Optional, recommended: least-privilege database users.
--
-- By default every component connects as `postgres`, which can do anything.
-- With these roles a leaked API connection string can't touch scraped data,
-- and a leaked scraper string can't read users' notification tokens.
--
-- 1. Run db/schema.sql first.
-- 2. Replace the three passwords below with long random ones, then run this
--    once in the Supabase SQL editor.
-- 3. Use the matching user in each DATABASE_URL (Supabase pooler format:
--    postgresql://ipo_api.<project-ref>:<password>@<pooler-host>:5432/postgres)
--      Render (API)              -> ipo_api
--      GitHub secret for scrape  -> ipo_scraper   (DATABASE_URL in daily_scrape)
--      GitHub secret for notify  -> ipo_notifier  (use a separate secret, e.g. NOTIFY_DATABASE_URL)

create role ipo_api      login password 'CHANGE-ME-api';
create role ipo_scraper  login password 'CHANGE-ME-scraper';
create role ipo_notifier login password 'CHANGE-ME-notifier';

grant usage on schema public to ipo_api, ipo_scraper, ipo_notifier;

-- API: read IPO data; manage devices and their tracked IPOs.
grant select on ipos, gmp_history to ipo_api;
grant select, insert, update, delete on users, user_tracked_ipos to ipo_api;

-- Scraper: write IPO data only. No access to users at all.
grant select, insert, update on ipos, gmp_history to ipo_scraper;
grant usage, select on sequence ipos_id_seq, gmp_history_id_seq to ipo_scraper;

-- Notifier: read what the digest needs; clear dead FCM tokens.
grant select on ipos, gmp_history, user_tracked_ipos to ipo_notifier;
grant select, update (fcm_token) on users to ipo_notifier;

-- Row level security is on for every table (schema.sql), which blocks
-- Supabase's public REST API. Let these roles through, and nobody else.
create policy ipos_read      on ipos              for select to ipo_api, ipo_notifier using (true);
create policy ipos_write     on ipos              for all    to ipo_scraper using (true) with check (true);
create policy gmp_read       on gmp_history       for select to ipo_api, ipo_notifier using (true);
create policy gmp_write      on gmp_history       for all    to ipo_scraper using (true) with check (true);
create policy users_api      on users             for all    to ipo_api using (true) with check (true);
create policy users_notify   on users             for select to ipo_notifier using (true);
create policy users_notify_u on users             for update to ipo_notifier using (true) with check (true);
create policy tracked_api    on user_tracked_ipos for all    to ipo_api using (true) with check (true);
create policy tracked_notify on user_tracked_ipos for select to ipo_notifier using (true);

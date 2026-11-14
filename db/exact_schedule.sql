-- Optional: start the two daily workflows at the exact time.
--
-- GitHub's built-in schedule is best-effort and can start hours late. This uses
-- Supabase's pg_cron + pg_net to call GitHub's "run workflow" API on time.
-- The schedule in the workflow files stays as a fallback.
--
-- Before running (Supabase > SQL editor):
--   1. Create a fine-grained GitHub token limited to this one repository with
--      the single permission  Actions: Read and write.
--   2. Replace OWNER/REPO (twice) and PASTE_TOKEN_HERE below. Never commit the token.
-- Safe to re-run: jobs are replaced by name. Times are UTC.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Keep the token encrypted in Supabase Vault, not in the job text.
delete from vault.secrets where name = 'github_dispatch_token';
select vault.create_secret('PASTE_TOKEN_HERE', 'github_dispatch_token');

create or replace function public.start_github_workflow(repo text, workflow text)
returns bigint
language sql
security definer
set search_path = ''
as $$
  select net.http_post(
    url := 'https://api.github.com/repos/' || repo || '/actions/workflows/' || workflow || '/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'Content-Type', 'application/json',
      'User-Agent', 'ipo-gmp-tracker-cron'
    ),
    body := '{"ref": "main"}'::jsonb
  );
$$;
revoke all on function public.start_github_workflow(text, text) from public, anon, authenticated;

-- 03:45 UTC = 09:15 IST scrape; 04:30 UTC = 10:00 IST digest.
select cron.schedule('ipo-gmp-scrape', '45 3 * * *', $$select public.start_github_workflow('OWNER/REPO', 'daily_scrape.yml')$$);
select cron.schedule('ipo-gmp-digest', '30 4 * * *', $$select public.start_github_workflow('OWNER/REPO', 'daily_notify.yml')$$);

-- Check later:  select * from cron.job_run_details order by start_time desc limit 5;
--               select status_code, content from net._http_response order by id desc limit 5;
-- Remove:       select cron.unschedule('ipo-gmp-scrape'); select cron.unschedule('ipo-gmp-digest');

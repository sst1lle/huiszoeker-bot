-- Idempotente notificatie-claim: INSERT … ON CONFLICT DO NOTHING RETURNING id

CREATE OR REPLACE FUNCTION claim_sent_notification(
  p_user_id uuid,
  p_listing_id uuid
)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  INSERT INTO sent_notifications (user_id, listing_id)
  VALUES (p_user_id, p_listing_id)
  ON CONFLICT (user_id, listing_id) DO NOTHING
  RETURNING id;
$$;

CREATE OR REPLACE FUNCTION claim_sent_notifications_batch(p_pairs jsonb)
RETURNS TABLE(id uuid, user_id uuid, listing_id uuid)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  INSERT INTO sent_notifications (user_id, listing_id)
  SELECT (elem->>'user_id')::uuid, (elem->>'listing_id')::uuid
  FROM jsonb_array_elements(p_pairs) AS elem
  WHERE (elem->>'user_id') IS NOT NULL
    AND (elem->>'listing_id') IS NOT NULL
  ON CONFLICT (user_id, listing_id) DO NOTHING
  RETURNING sent_notifications.id, sent_notifications.user_id, sent_notifications.listing_id;
$$;

GRANT EXECUTE ON FUNCTION claim_sent_notification(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION claim_sent_notifications_batch(jsonb) TO service_role;

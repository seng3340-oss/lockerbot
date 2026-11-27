string STORE=STORE
string RETURN=RETURN
string SUCCESS=SUCCESS
string FAILED_UNCHANGED=FAILED_UNCHANGED
string UNKNOWN=UNKNOWN

# A confirmed physical outcome for ONE registered item, not an instruction.
# Stable across retries; unique across attendance and item events.
string event_id
string user_id
string item_id
string action
string outcome
string target_location
builtin_interfaces/Time occurred_at
# Preserve the exact ItemState.updated_at observed BEFORE the operation.
string expected_updated_at
# Required for FAILED_UNCHANGED and UNKNOWN.
string reason

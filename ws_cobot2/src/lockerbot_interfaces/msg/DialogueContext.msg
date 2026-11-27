string YES_NO=YES_NO
string ITEM_SELECTION=ITEM_SELECTION
string FREE_TEXT=FREE_TEXT

std_msgs/Header header
string session_id
string task_id
# Empty question_id clears the active question.
string question_id
string question_type
string prompt
# Human-readable plan, not executable robot instructions.
string plan_summary
string[] candidate_item_ids
builtin_interfaces/Time expires_at

uint8 IDLE=0
uint8 CAMERA=1
uint8 TEXT=2
uint8 PROGRESS=3
uint8 ERROR=4

uint8 AUTH_UNKNOWN=0
uint8 AUTH_VERIFIED=1
uint8 AUTH_REJECTED=2

std_msgs/Header header
string device_id
string session_id
# Unique UI event ID; receivers deduplicate speech by this ID.
string event_id
uint8 screen_mode
uint8 auth_state
bool camera_enabled
string user_id
string display_name
string text
bool speak
# [0, 1]; -1 when progress is unavailable.
float32 progress
# Clear user information, preview and queued speech when ending the session.
bool clear_session

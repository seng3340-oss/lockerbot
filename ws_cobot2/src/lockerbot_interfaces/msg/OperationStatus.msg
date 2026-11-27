# Application status. ROS action acceptance/terminal state is separate.
uint16 OK=0
uint16 INVALID_REQUEST=1
uint16 BUSY=2
uint16 SESSION_EXPIRED=3
uint16 QUESTION_EXPIRED=4
uint16 NOT_RECOGNIZED=5
uint16 IDENTITY_MISMATCH=6
uint16 NOT_FOUND=7
uint16 POSE_INVALID=8
uint16 TIMEOUT=9
uint16 CANCELLED=10
uint16 PARTIAL_FAILURE=11
uint16 EXECUTION_FAILED=12
uint16 STATE_UNKNOWN=13
uint16 EVENT_CONFLICT=14
uint16 STALE_STATE=15
uint16 STORAGE_ERROR=16
uint16 OWNERSHIP_ERROR=17

# success iff code == OK. Failure requires an explanatory message.
bool success
uint16 code 1
string message

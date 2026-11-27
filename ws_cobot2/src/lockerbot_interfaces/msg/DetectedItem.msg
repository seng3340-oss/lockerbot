# Observation identity is not a database item identity.
string detection_id
# Empty unless associated with a registered individual item by the caller.
string item_id
string label
float32 confidence
geometry_msgs/PoseStamped grasp_pose
bool pose_valid
builtin_interfaces/Time valid_until
bool occluded

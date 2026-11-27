cmake_minimum_required(VERSION 3.8)
project(lockerbot_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(action_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/OperationStatus.msg"
  "msg/AudioChunk.msg"
  "msg/TabletState.msg"
  "msg/DialogueContext.msg"
  "msg/DetectedItem.msg"
  "msg/ItemState.msg"
  "msg/ItemResult.msg"
  "msg/AttendanceEvent.msg"
  "srv/StartSession.srv"
  "srv/SubmitAnswer.srv"
  "srv/GetItems.srv"
  "srv/RecordAttendance.srv"
  "srv/RecordItemResult.srv"
  "action/ExecuteTask.action"
  "action/IdentifyUser.action"
  "action/DetectItems.action"
  "action/ExecuteRobotStep.action"
  DEPENDENCIES action_msgs builtin_interfaces geometry_msgs std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()

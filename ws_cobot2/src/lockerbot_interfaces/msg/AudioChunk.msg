# PCM signed 16-bit little-endian, interleaved channels.
std_msgs/Header header
string device_id
# Empty before session start, assigned by StartSession afterward.
string session_id
# Increases per (device_id, stream_id); reset only with a new stream_id.
string stream_id
uint64 sequence
uint32 sample_rate_hz
uint8 channels
uint8[] pcm_s16le

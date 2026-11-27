string BELONGING=BELONGING
string ACCESS_CARD=ACCESS_CARD
string WITH_USER=WITH_USER
string STORED=STORED
string ON_TRAY=ON_TRAY
string UNKNOWN=UNKNOWN

string item_id
string owner_id
string name
string kind
string status
# Empty represents DB NULL; UNKNOWN always has empty location.
string location
# Exact UTC ISO-8601 string from Storage.list_items(), including microseconds.
string updated_at
# All three empty if no confirmed observation exists.
string last_confirmed_status
string last_confirmed_location
string last_confirmed_at

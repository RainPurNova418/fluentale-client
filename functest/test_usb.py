# test_usb.py
from toolmethods import list_removable_drives, get_volume_serial, get_volume_label, get_usb_id

drives = list_removable_drives()
print("检测到可移动磁盘:", drives)

for d in drives:
    serial = get_volume_serial(d)
    label = get_volume_label(d)
    usb_id = get_usb_id(d)
    print(f"  {d}  label={label!r}  serial={serial}  id={usb_id}")
# Simple JuiceBox Service

This service will do simple JuiceBox setting updates and schedule management.

```
usage: juiceboxservice.py [-h] [-i CURRENT] [-s SCHEDULE] [-l LOG]

options:
  -h, --help            show this help message and exit
  -i CURRENT, --current CURRENT
                        Set current available in amps (default 40)
  -s SCHEDULE, --schedule SCHEDULE
                        Scheduled charging (hh:mm-hh:mm)
  -l LOG, --log LOG     Log data to this file
```

## Dependencies

* Requires [https://github.com/philipkocanda/juicebox-protocol] or this fork [https://github.com/potatono/juicebox-protocol] on newer devices.
* DNS of `juicenet-udp-prod-usa.enelx.com` needs to point to service host

## Notes

* You can telnet to the juicebox on port 2000 and update the udpc endpoint to point to your service and it will appear to work, but the juicebox will not receive any of the commands you send it.  Updating the endpoint breaks the open stream.
* Disabling and enabling charging is done by setting current available to zero/non-zero.
* Scheduling is handled by the service, just turning it on when inside the schedule time.  This is how the Enel service was handling scheduling.  AFAIK the box does not have it's own scheduling feature.
* The `juicebox-protocol` library references offline (device default) and instant current settings, but they appear to be reversed.  This tool just sets both every time, which matches the observed Enel service behavior.
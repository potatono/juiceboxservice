import argparse
import socket
import time
import re
import sys
import os
from datetime import datetime

from juicebox.message import Message as ServiceMessage

class DeviceMessage:
    xlat = {
        'v': { 'name':'version', 'type':str },
        'A': { 'name':'current', 'type':float, 'mult': 0.1 },
        'u': { 'name':'loop_counter', 'type':int },
        'V': { 'name':'voltage', 'type':float, 'mult': 0.1 },
        'L': { 'name':'lifetime', 'type':int },
        'S': { 'name':'status', 'type':int, 
               'enum': ['unplugged', 'plugged-in',
                       'charging', 'not-defined',
                       'error'] },
        'T': { 'name':'temperature', 'type':float, 
               'mult': 1.8, 'ofs': 32 },
        'M': { 'name':'current_default', 'type':int },
        'm': { 'name':'current_rating', 'type':int },
        't': { 'name':'report_time', 'type':int },
        'i': { 'name':'interval', 'type':int },
        'f': { 'name':'frequency', 'type':float, 'mult': 0.01 },
        's': { 'name':'sequence', 'type':int },
        'F': { 'name':'F', 'type':int },
        'C': { 'name':'current_available', 'type':int },
        'e': { 'name':'e', 'type':int },
        'r': { 'name':'r', 'type':int },
        'b': { 'name':'b', 'type':int },
        'B': { 'name':'B', 'type':int },
        'p': { 'name':'p', 'type':int },
        'E': { 'name':'E', 'type':int },
        'P': { 'name':'P', 'type':int },
    }

    def __init__(self):
        self.device_id = None
        self.payload = ""
        self.crc = None
        self.payload_type = "data"

    def __str__(self):
        if self.payload_type == "data":
            return f"Device Status:{self.status}, Current:{self.current}, Current Available:{self.current_available}"
        
        return self.payload
    
    @staticmethod
    def xlat_payload_part(part):
        cmd = part[0]
        val = part[1:]

        if cmd not in DeviceMessage.xlat:
            print(f"Unknown cmd: {cmd}")
        else:
            xlat = DeviceMessage.xlat[cmd]
            cmd = xlat['name']
            val = xlat['type'](val)
            if 'mult' in xlat:
                val = val * xlat['mult']

            if 'ofs' in xlat:
                val = val + xlat['ofs']
    
            if 'enum' in xlat:
                val = xlat['enum'][val]

        return (cmd, val)

    @staticmethod
    def from_string(msg):
        self = DeviceMessage()
        self.payload = msg
        pat = "^(\d+):([\-\w,]+)!(\w+):"
        mat = re.search(pat, msg)
        
        if mat is not None:
            self.device_id = mat.groups()[0]
            payload = mat.groups()[1]
            self.crc = mat.groups()[2]

            parts = payload.split(',')

            for part in parts:
                (cmd, val) = DeviceMessage.xlat_payload_part(part)
                setattr(self, cmd, val)
            
            if not hasattr(self,'current'):
                self.current = 0

        else:
            pat = "^(\d+):DBG,(\w+):(.+?):$"
            mat = re.search(pat, msg)

            if mat is not None:
                self.device_id = mat.groups()[0]
                self.debug_level = mat.groups()[1]
                self.debug_message = mat.groups()[2]
                self.payload_type = 'debug'
        
        return self

class JuiceboxService:
    # I think the "command" is actually a set of flags, but I still don't know what they do.
    #
    # 6 - 0000 0110
    # 242 1111 0010
    # 8 - 0000 1000
    # 244 1111 0100 
    #
    # The Enel service typically sends the command in the following sequence so we'll just
    # emulate that behavior
    cmd_seq = [ 6, 242, 8, 244 ]

    def __init__(self):
        self.init_args()
        self.init_socket()

    def init_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("-i", "--current", help="Set current available in amps (default 40)", type=int, default=40)
        parser.add_argument("-s", "--schedule", help="Scheduled charging (hh:mm-hh:mm)")
        parser.add_argument("-l", "--log", help="Log data to this file")
        self.args = parser.parse_args()

        self.start_hour = 0
        self.start_min = 0
        self.end_hour = 23
        self.end_min = 59

        if self.args.schedule:
            mat = re.search("(\d+):(\d+)-(\d+):(\d+)", self.args.schedule)
            if mat is None:
                print("Invalid schedule.  Exiting.")
                sys.exit(1)

            (self.start_hour, self.start_min, 
             self.end_hour, self.end_min) = [int(i) for i in mat.groups()]

        if self.args.log and not os.path.exists(self.args.log):
            with open(self.args.log, "w") as logfile:
                print("date,status,current,voltage,temperature,lifetime", file=logfile)
    
    def init_socket(self):
        self.socket = socket.socket(
                family=socket.AF_INET, 
                type=socket.SOCK_DGRAM)

        self.socket.bind(('0.0.0.0', 8043))

    # Updates the message counter/sequence, increments it, and 
    # then sets command to emulate the observed Enel behavior
    def update_sequence(self, smsg, sequence=None):
        if sequence is not None:
            smsg.counter = sequence

        smsg.counter += 1
        if smsg.counter > 999:
            smsg.counter = 1

        smsg.command = self.cmd_seq[smsg.counter % 4]
        return smsg

    def save_data(self, dmsg):
        if self.args.log:
            with open(self.args.log, "a") as logfile:
                row = [
                    str(datetime.now()),
                    dmsg.status,
                    str(dmsg.current),
                    str(dmsg.voltage),
                    str(dmsg.temperature),
                    str(dmsg.lifetime)
                ]

                print(','.join(row), file=logfile)

    def create_reply_message(self, dmsg):
        smsg = ServiceMessage()
        smsg.offline_amperage = dmsg.current_default
        smsg.instant_amperage = dmsg.current_available
        self.update_sequence(smsg, dmsg.sequence)

        if hasattr(smsg, "version"):
            smsg.version = dmsg.version

        return smsg
        
    def get_next_device_message(self):
        print("Waiting on packet from JuiceBox device..")

        (pkt, address) = self.socket.recvfrom(1024)   
        msg = pkt.decode('ascii')
        dmsg = DeviceMessage.from_string(msg)
        
        print("<<", msg)
        print(dmsg)
    
        return (dmsg, address)
    
    def send_message(self, smsg, address):
        msg = smsg.build()
        print(f"Service current setting:{smsg.instant_amperage}")
        print(">>", msg)
        data = bytes(msg, encoding='ascii')
        
        self.socket.sendto(data, address)

    def is_in_schedule(self):
        now = datetime.now()
        hour = now.time().hour
        min = now.time().minute

        after_start = (hour >= self.start_hour and min >= self.start_min)
        before_end = (hour <= self.end_hour and min <= self.end_min)

        if self.start_hour < self.end_hour:
            return after_start and before_end
        else:
            return after_start or before_end

    def current_change_value(self, dmsg):
        current = dmsg.current_available
        in_schedule = self.is_in_schedule()

        if in_schedule and current != self.args.current:
            return self.args.current
        elif not in_schedule and current > 0:
            return 0
        
        return None

    def create_update_message(self, smsg, change_value):
        smsg.offline_amperage = change_value
        smsg.instant_amperage = change_value
        self.update_sequence(smsg)
        smsg.payload_str = None
        smsg.build()

        return smsg

    def run(self):
        while True:
            # Blocking wait for next message from the JuiceBox
            (dmsg, address) = self.get_next_device_message()

            # If we get a non-data message then do not reply
            if dmsg.payload_type != "data":
                continue

            # Save the data out to a log if we're using it
            self.save_data(dmsg)

            # The Enel service did not reply right away, so we'll
            # take a short pause
            time.sleep(4)

            # Create a reply based on the message received
            smsg = self.create_reply_message(dmsg)
            
            # Send the reply
            self.send_message(smsg, address)

            # The Enel service would typically send an update after
            # it had replied.  If the data needs to be changed we'll
            # send another message now
            change_value = self.current_change_value(dmsg)
            if change_value is not None:
                print(f"Changing current value to {change_value}.")
                time.sleep(1)

                self.create_update_message(smsg, change_value)

                self.send_message(smsg, address)

if __name__ == "__main__":
    service = JuiceboxService()
    service.run()

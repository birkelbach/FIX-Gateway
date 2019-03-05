#!/usr/bin/env python

#  Copyright (c) 2014 Phil Birkelbach, Neil Domalik
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import threading
import os
import xml.etree.ElementTree as ET
import socket
import fixgw.plugin as plugin

items = []
var_sep = ','

msg_send = 0

class UDPClient(threading.Thread):
    def __init__(self, host, port):
        super(UDPClient, self).__init__()

        UDP_IP = host
        UDP_PORT = int(port)

        self.sock = socket.socket(socket.AF_INET,  # Internet
                             socket.SOCK_DGRAM)  # UDP
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.settimeout(2.0)
        self.sock.bind((UDP_IP, UDP_PORT))
        self.getout = False
        self.msg_recv = 0

    def save_data(self, data):
        #print(data)
        l = data.split(var_sep)
        for i, each in enumerate(l):
            items[i].value = each

    def run(self):
        buff = ""
        while not self.getout:
            #Reads the UDP packet splits then sends it to the Queue
            try:
                data = self.sock.recv(1024)  # buffer size is 1024 bytes
                if data:
                    for d in data.decode('utf-8'):
                        if d != '\n':
                            buff += d
                        else:
                            self.save_data(buff)
                            self.msg_recv += 1
                            buff = ""
            except socket.timeout:
                pass
        self.running = False

    def stop(self):
        self.getout = True


class Item(object):
    def __init__(self, key):
        self.key = key
        self.item = None
        self.type = ""
        self.conversion = None

    def setValue(self, x):
        if self.item != None:
            if self.conversion != None:
                self.item.value = self.conversion(x)
            else:
                self.item.value = x

    def getValue(self, x):
        if self.item != None:
            return self.item.value
        else:
            return None

    value = property(getValue, setValue)

    def __str__(self):
        return self.key




class MainThread(threading.Thread):
    def __init__(self, parent):
        super(MainThread, self).__init__()
        self.getout = False
        self.parent = parent
        self.log = parent.log
        self.config = parent.config

    def run(self):
        self.clientThread = UDPClient(self.config['host'], self.config['out_port'])
        self.clientThread.start()

    def stop(self):
        self.clientThread.stop()


# We use closures for the conversion functions
def getMultiplyFunction(value):
    def Function(x):
        return float(x) * value
    return Function

def getFtoCFunction(value):
    def Function(x):
        return (float(x)-32)*5/9
    return Function

functions = {"multiply":getMultiplyFunction,
             "ftoc":getFtoCFunction}

def getConversion(fd):
    f = fd["function"].lower()
    value = float(fd.get("value", 1.0))
    if f in functions:
        return functions[f](value)
    else:
        raise KeyError("{} is not a valid function".format(f))


class Plugin(plugin.PluginBase):
    def __init__(self, name, config):
        super(Plugin, self).__init__(name, config)
        self.thread = MainThread(self)

    def run(self):
        try:
            self.xml_list = self.parseProtocolFile(self.config['fg_root'],
                                                   self.config['xml_file'])
        except Exception as e:
            self.log.critical(e)
            self.stop()
            return

        # This loop checks to see if we have each item in the database
        # if not then we'll just let it get set to None and ignore it when
        # we parse the string from FlightGear
        for each in items:
            each.item = self.db_get_item(each.key)
            if each.item == None:
                self.log.warning("{0} found in protocol file but not in the database".format(each.key))

        self.thread.start()

    def stop(self):
        try:
            self.thread.stop()
        except AttributeError:
            pass
        if self.thread.is_alive():
            self.thread.join(2.0)
        if self.thread.is_alive():
            raise plugin.PluginFail

    def get_status(self):
        d = {"Properties":len(items),
             "Messages": {
                 "Received": self.thread.clientThread.msg_recv,
                 "Sent": 0 }
            }
        return d


    def parseProtocolFile(self, fg_root, xml_file):
        # Open the XML Protocol file
        filepath = os.path.join(fg_root, "Protocol/" + xml_file)

        tree = ET.parse(filepath)
        root = tree.getroot()
        if root.tag != "PropertyList":
            raise ValueError("Root Tag is not PropertyList")

        # TODO Read var_separator tag and adjust accordingly
        # TODO Get conversion if any and set conversion function
        generic = root.find("generic")
        output = generic.find("output")
        for chunk in output:
            name = chunk.find("name")
            if name != None:
                info = name.text.split(":")
                i = Item(info[0].strip())
                conversion = chunk.find("conversion")
                if conversion != None:
                    try:
                        i.conversion = getConversion(conversion.attrib)
                    except Exception as e:
                        self.log.error("Problem with conversion definition for {} - {}".format(name.text, e))

                items.append(i)

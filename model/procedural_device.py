'''Device model using json credentials and supporting script commands'''
import os
from typing import Union # to use Union[Enum, None] type hint
from enum import Enum
import subprocess
import struct
from iotconnect import IoTConnectSDK
from datetime import datetime
from model.enums import Enums as E
from model.iotc_pipe import IOTCPipe, DEFAULT_PIPE_PATH
import json


class DynAttr:

    name = None
    path = None
    read_type = None

    def __init__(self, name, path,read_type):
        self.name = name
        self.path = path
        self.read_type = read_type

    def update_value(self):
        val = None
        try:
            if self.read_type == E.ReadTypes.ascii:
                with open(self.path, "r", encoding="utf-8") as f:
                    val = f.read()

            if self.read_type == E.ReadTypes.binary:
                with open(self.path, "rb") as f:
                    val = f.read()

        except FileNotFoundError:
            print("File not found at", self.path)
        return val

    def get_value(self,to_type):
        val = self.update_value()
        if to_type is not None:
            val = self.convert(val,to_type)
        return val
    
    def convert(self,val,to_type):
        if self.read_type == E.ReadTypes.binary:
            if to_type in [E.SendDataTypes.INT, E.SendDataTypes.LONG]:
                return int.from_bytes(val, 'big')
            
            elif to_type in [E.SendDataTypes.FLOAT]:
                return (struct.unpack('f', val)[0])
            
            elif to_type in [E.SendDataTypes.STRING]:
                return val.decode("utf-8")
            
            elif to_type in [E.SendDataTypes.Boolean]:
                return struct.unpack('?', val)[0]
            
            elif to_type in [E.SendDataTypes.BIT]:
                if struct.unpack('?', val)[0]:
                    return 1
                return 0

        if self.read_type == E.ReadTypes.ascii:
            try:
                if to_type in [E.SendDataTypes.INT, E.SendDataTypes.LONG]:
                    return int(float(val))
                
                elif to_type in [E.SendDataTypes.FLOAT]:
                    return float(val)
                
                elif to_type in [E.SendDataTypes.STRING]:
                    return str(val)
                
                elif to_type in [E.SendDataTypes.BIT]:
                    if self.convert(val, E.SendDataTypes.INT) != 0:
                        return 1
                    return 0
                
                elif to_type in [E.SendDataTypes.Boolean]:
                    if type(val) == bool:
                        return val
                    
                    elif type(val) == int:
                        return val != 0
                    
                    elif type(val) == str:
                        if val in ["False", "false", "0", ""]:
                            return False
                        return True
                    
            except Exception as exception:
                print(exception)
        return None

class ProceduralDevice():
    attributes: DynAttr = []
    # attributes is a list of attributes brought in from json
    # the DynAttr class holds the metadata only, E.g. where the value is saved as a file - the attribute itself is set on the class
    
    parsed_json: dict = {}
    SCRIPTS_PATH:str = ""
    scripts: list = []
    needs_exit:bool = False
    in_ota:bool = False
    attribute_metadata: list = None
    send_only_templated_attributes:bool = False

    def __init__(self, conf_file):
    
        # Get Json
        j: json = None
        with open(conf_file, "r", encoding="utf-8") as file:
            f_contents = file.read()
            j = json.loads(f_contents)

        # Validate Json
        test = 'duid'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'cpid'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'env'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'iotc_server_cert'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'sdk_id'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'discovery_url'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'connection_type'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'auth'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'auth_type'
        if test not in j['auth']:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'params'
        if test not in j['auth']:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'device'
        if test not in j:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'commands_list_path'
        if test not in j['device']:
            raise ValueError(f"ERROR - {test} not in json")
        
        test = 'attributes'
        if test not in j['device']:
            raise ValueError(f"ERROR - {test} not in json")

        # assign variables from Json
        self.auth_type = j['auth']['auth_type']
        self.discovery_url = j['discovery_url']
        self.sdk_id = j['sdk_id']
        self.iotc_server_cert = j['iotc_server_cert']
        self.environment = j['env']
        self.company_unique_id = j['cpid']
        self.device_unique_id = j['duid']

        self.SCRIPTS_PATH = j['device']['commands_list_path'] 

        connection_type = j['connection_type']
        self.platform = ""
        if connection_type == "IOTC_CT_AZURE":
            self.platform = "az"
        if connection_type == "IOTC_CT_AWS":
            self.platform = "aws"

        attributes = j['device']['attributes']
        for attr in attributes:
            m_att = DynAttr(attr["name"],attr["private_data"],attr["private_data_type"])
            self.attributes.append(m_att)
        
        sdk_options = {}
        sdk_options.update({'cpid': self.company_unique_id})

        # sdk_id causes problems for now
        # sdk_options.update({'sId': sdk_id})

        sdk_options.update({'env': self.environment})
        sdk_options.update({'pf': self.platform})
        sdk_options.update({'discoveryUrl' : self.discovery_url})

        if self.auth_type == "IOTC_AT_X509":
            test = 'client_key'
            if test not in j['auth']['params']:
                raise ValueError(f"ERROR - {test} not in json")
            
            test = 'client_cert'
            if test not in j['auth']['params']:
                raise ValueError(f"ERROR - {test} not in json")
            
            client_key = j['auth']['params']['client_key']
            client_cert = j['auth']['params']['client_cert']
            
            certificate = { 
                "SSLKeyPath"  : client_key,
                "SSLCertPath" : client_cert,
                "SSLCaPath"   : self.iotc_server_cert,
            }
            sdk_options.update({"certificate" : certificate})
        self.sdk_options = sdk_options

        
        self.get_all_scripts()

    def connect(self):
        self.SdkClient = IoTConnectSDK(
            uniqueId=self.device_unique_id,
            # sId=self.sdk_id,
            # cpid=self.company_unique_id,
            #env=self.environment,
            sdkOptions=self.sdk_options,
            initCallback=self.init_cb)
        
        self.bind_callbacks()
        self.SdkClient.GetAttributes(self.get_attribute_metadata_from_cloud)

    def get_attribute_metadata_from_cloud(self, msg):
        self.attribute_metadata = []
        for meta_dict in msg:
            if E.Keys.data in meta_dict:
                self.attribute_metadata = meta_dict[E.Keys.data]

    def module_cb(self,msg):
        raise NotImplementedError()

    def twin_change_cb(self,msg):
        raise NotImplementedError()

    def attribute_change_cb(self,msg):
        self.SdkClient.GetAttributes(self.get_attribute_metadata_from_cloud)

    def device_change_cb(self,msg):
        raise NotImplementedError()

    def rule_change_cb(self,msg):
        raise NotImplementedError()

    def init_cb(self, msg):
        if E.get_value(msg, E.Keys.command_type) is E.Values.Commands.INIT_CONNECT:
            print("connection status is " + msg["command"])
        
    def bind_callbacks(self):
        self.SdkClient.onOTACommand(self.ota_cb)
        self.SdkClient.onModuleCommand(self.module_cb)
        self.SdkClient.onTwinChangeCommand(self.twin_change_cb)
        self.SdkClient.onAttrChangeCommand(self.attribute_change_cb)
        self.SdkClient.onDeviceChangeCommand(self.device_change_cb)
        self.SdkClient.onRuleChangeCommand(self.rule_change_cb)
        self.SdkClient.onDeviceCommand(self.device_cb)

    def send_device_states(self):

        # Don't send anything till we get our cloud attributes
        if self.send_only_templated_attributes and self.attribute_metadata is None:
            return

        data_array = [self.get_d2c_data()]
        # if self.children is not None:
        #     for child in self.children:
        #         data_array.append(child.get_d2c_data())

        for data in data_array:
            self.send_d2c(data)
        return data_array

    def send_d2c(self, data):
        if self.SdkClient is not None:
            self.SdkClient.SendData(data)
        else:
            print("no client")

    def send_ack(self, msg, status: E.Values.AckStat, message):
        # check if ack exists in message
        if E.get_value(msg, E.Keys.ack) is None:
            print("Ack not requested, returning")
            return
        
        id_to_send = E.get_value(msg, E.Keys.id)
        self.SdkClient.sendAckCmd(msg[E.Keys.ack], status, message, id_to_send)


    class DeviceCommands(Enum):
        EXEC = "exec"

        @classmethod
        def get(cls, command:str) -> Union[Enum, None]:
            '''Validates full command string against accepted enumerated commands'''
            if command in [dc.value for dc in cls]:
                    return cls(command)
            return None


    def get_d2c_data(self):
        data_obj = [{
            "uniqueId": self.device_unique_id,
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "data": self.get_state()
        }]
        return data_obj
    
        
    def generate_d2c_data(self, data):
        data_obj = [{
            "uniqueId": self.device_unique_id,
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "data": data
        }]
        return data_obj

    def get_state(self):
        '''Do not override'''
        data_obj = {}
        data_obj.update(self.get_attributes_state())
        data_obj.update(self.get_local_state())
        return data_obj
    
    def get_attributes_state(self) -> dict:
        '''Gets all attributes specified from the JSON file'''
        data_obj = {}
        attribute: DynAttr
        for attribute in self.attributes:
            if self.send_only_templated_attributes:
                for metadata in self.attribute_metadata:
                    if attribute.name == metadata[E.MetadataKeys.name]:
                        data_obj[attribute.name] = attribute.get_value(metadata[E.MetadataKeys.data_type])
                        break
            else:
                #Send everything raw        
                data_obj[attribute.name] = attribute.get_value(None)
        
        return data_obj
    
    def get_local_state(self) -> dict:
        '''Over-rideable - return dictionary of local data to send to the cloud'''
        return {}

    def ota_cb(self,msg):
        from model.ota_handler import OtaHandler
        OtaHandler(self,msg)
    
    def get_all_scripts(self):
        if not self.SCRIPTS_PATH.endswith('/'):
            self.SCRIPTS_PATH += '/'
        self.scripts: list = [f for f in os.listdir(self.SCRIPTS_PATH) if os.path.isfile(os.path.join(self.SCRIPTS_PATH, f))]

    def device_cb(self,msg):
        # Only handles messages with E.Values.Commands.DEVICE_COMMAND (also known as CMDTYPE["DCOMM"])
        command: list = E.get_value(msg, E.Keys.device_command).split(' ')
        
        # If you need to implement other hardcoded commands
        # add the command name to the DeviceCommands enum
        # and check against it here (see the comment below)

        # enum_command = self.DeviceCommands.get(command[0])
        # if enum_command == self.DeviceCommands.EXAMPLE:
        #     do something

        # if command exists in scripts folder append the folder path
        if command[0] in self.scripts:
            command[0] = self.SCRIPTS_PATH + command[0]

            process = subprocess.run(command, check=False, capture_output=True)
            process_success:bool = (process.returncode == 0)

            ack = E.Values.AckStat.SUCCESS if process_success else E.Values.AckStat.FAIL
            process_output: bytes = process.stdout #if process_success else process.stderr
        
            ack_message = str(process_output, 'UTF-8')
            self.send_ack(msg,ack, ack_message)
            return

        self.send_ack(msg,E.Values.AckStat.FAIL, f"Command {command[0]} does not exist")

    def send_from_pipe(self):
        from_pipe = IOTCPipe.read_object()
        if from_pipe is not None:
            if isinstance(from_pipe, dict):
                data_sent = self.send_d2c(self.generate_d2c_data(from_pipe))


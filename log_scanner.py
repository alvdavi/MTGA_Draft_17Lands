import os
import time
import json
import logging
import sys
import card_logic as CL
import file_extractor as FE
from collections import OrderedDict

# Global Constants
## The different types of draft.
LIMITED_TYPE_UNKNOWN            = 0
LIMITED_TYPE_DRAFT_PREMIER_V1   = 1
LIMITED_TYPE_DRAFT_PREMIER_V2   = 2
LIMITED_TYPE_DRAFT_QUICK        = 3
LIMITED_TYPE_DRAFT_TRADITIONAL  = 4
LIMITED_TYPE_SEALED             = 5
LIMITED_TYPE_SEALED_TRADITIONAL = 6

NON_COLORS_OPTIONS = ["Auto", "All GIHWR", "All IWD", "All ALSA"]
DECK_COLORS = ["All Decks","W","U","B","R","G","WU","WB","WR","WG","UB","UR","UG","BR","BG","RG","WUB","WUR","WUG","WBR","WBG","WRG","UBR","UBG","URG","BRG"]
DECK_FILTERS = NON_COLORS_OPTIONS + DECK_COLORS

DRAFT_LOG_FOLDER = os.path.join(os.getcwd(), "./Logs")

SET_FILE_SUFFIX = "Data.json"
TIER_FILE_PREFIX = "Tier_"

DATA_SOURCES_NONE = {"None" : ""}

#Dictionaries
## Used to identify the limited type based on log string
limited_types_dict = {
    "PremierDraft"     : LIMITED_TYPE_DRAFT_PREMIER_V1,
    "QuickDraft"       : LIMITED_TYPE_DRAFT_QUICK,
    "TradDraft"        : LIMITED_TYPE_DRAFT_TRADITIONAL,
    "BotDraft"         : LIMITED_TYPE_DRAFT_QUICK,
    "Sealed"           : LIMITED_TYPE_SEALED,
    "TradSealed"       : LIMITED_TYPE_SEALED_TRADITIONAL,
}

class ArenaScanner:
    def __init__(self, filename, step_through):
        self.arena_file = filename
        
        self.logger = logging.getLogger("draftLog")
        self.logger.setLevel(logging.INFO)
        
        self.logging_enabled = True
        
        self.step_through = step_through
        self.set_data = None
        self.draft_type = LIMITED_TYPE_UNKNOWN
        self.pick_offset = 0
        self.pack_offset = 0
        self.search_offset = 0
        self.draft_set = None
        self.current_pick = 0
        self.picked_cards = [[] for i in range(8)]
        self.taken_cards = []
        self.sideboard = []
        self.pack_cards = [[]] * 8
        self.initial_pack = [[]] * 8
        self.current_pack = 0
        self.previous_picked_pack = 0
        self.current_picked_pick = 0
        self.file_size = 0
        self.data_source = "None"

    def ArenaFile(self, filename):
        self.arena_file = filename

    def LogEnable(self, enable):
        self.logging_enabled = enable
        self.LogSuspend(not enable)

    def LogSuspend(self, suspended):
        if suspended:
            self.logger.setLevel(logging.CRITICAL)
        elif self.logging_enabled:
            self.logger.setLevel(logging.INFO)

    def NewLog(self, set, event):
        log_name = f"DraftLog_{set}_{event}_{int(time.time())}.log"
        log_path = os.path.join(DRAFT_LOG_FOLDER, log_name)
        for handler in self.logger.handlers:
            if isinstance(handler, logging.FileHandler):
                self.logger.removeHandler(handler)
        formatter = logging.Formatter('%(asctime)s,%(message)s', datefmt='<%d%m%Y %H:%M:%S>')
        new_handler = logging.FileHandler(log_path, delay=True)
        new_handler.setFormatter(formatter)
        self.logger.addHandler(new_handler)

    def ClearDraft(self, full_clear):
        if full_clear:
            self.search_offset = 0
            self.file_size = 0
        self.set_data = None
        self.draft_type = LIMITED_TYPE_UNKNOWN
        self.pick_offset = 0
        self.pack_offset = 0
        self.draft_set = None
        self.current_pick = 0
        self.picked_cards = [[] for i in range(8)]
        self.taken_cards = []
        self.sideboard = []
        self.pack_cards = [[]] * 8
        self.initial_pack = [[]] * 8
        self.current_pack = 0
        self.previous_picked_pack = 0
        self.current_picked_pick = 0
        self.data_source = "None"
        
    def DraftStartSearch(self): 
        update = False
        #Open the file
        switcher={
                "[UnityCrossThreadLogger]==> Event_Join " : (lambda x, y: self.DraftStartSearchV1(x, y)),
                "[UnityCrossThreadLogger]==> Event.Join " : (lambda x, y: self.DraftStartSearchV2(x, y)),
                "[UnityCrossThreadLogger]==> BotDraft_DraftStatus " : (lambda x, y: self.DraftStartSearchV1(x, y)),
             }
        
        
        try:
            #Check if a new player.log was created (e.g. application was started before Arena was started)
            if self.file_size > os.path.getsize(self.arena_file):
                self.ClearDraft(True)
            self.file_size = os.path.getsize(self.arena_file)
            offset = self.search_offset
            previous_draft_type = self.draft_type
            previous_draft_set = self.draft_set
            with open(self.arena_file, 'r') as log:
                log.seek(offset)
                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    for search_string in switcher.keys():
                        string_offset = line.find(search_string)
                        if string_offset != -1:
                            self.search_offset = offset
                            start_parser = switcher.get(search_string, lambda: None)
                            event_data = json.loads(line[string_offset + len(search_string):])
                            start_parser(event_data, offset)
                            self.logger.info(line)
                            break
                                
            if (self.draft_type != LIMITED_TYPE_UNKNOWN) and \
               ((self.draft_type != previous_draft_type) or \
                (self.draft_set != previous_draft_set)):
                self.pick_offset = self.search_offset 
                self.pack_offset = self.search_offset
                update = True

        except Exception as error:
            print("DraftStartSearch Error: %s" % error)
            
        return update
    def DraftStartSearchV1(self, event_data, offset):
        try:
            request_data = json.loads(event_data["request"])
            payload_data = json.loads(request_data["Payload"])
            event_name = payload_data["EventName"]
            
            event_string = event_name.split('_')
            
            if len(event_string) > 1:
                #Trad_Sealed_NEO_20220317
                for count, event in enumerate(event_string):
                    if event in limited_types_dict.keys() or event == "Sealed":
                        if event == "Sealed":
                            event_type = "TradSealed" if event_string[0] == "Trad" else "Sealed"
                            event_set = event_string[count + 1]
                        else:
                            event_type = event
                            if count == 0:
                                event_set = event_string[count + 1]
                            else:
                                event_set = event_string[count - 1]
                
                        self.draft_type = limited_types_dict[event_type]
                        self.draft_set = event_set.upper()
                        self.NewLog(event_set, event_type)
                        #directory = "Logs/"
                        #self.diag_log_file = directory + "DraftLog_%s_%s_%u.log" % (event_set, event_type, int(time.time()))
                        break
        except Exception as error:
            print("DraftStartSearchV1 Error: %s" % error)
            
    
    def DraftStartSearchV2(self, event_data, offset):
        try:
            request_data = json.loads(event_data["request"])
            params_data = request_data["params"]
            event_name = params_data["eventName"]
            
            event_string = event_name.split('_')
            
            if len(event_string) > 1:
                event_type = event_string[0]
                event_set = event_string[1]
                
                if event_type in limited_types_dict.keys():
                    self.draft_type = limited_types_dict[event_type]
                    self.draft_set = event_set.upper()
                    self.NewLog(event_set, event_type)
                    #directory = "Logs/"
                    #self.diag_log_file = directory + "DraftLog_%s_%s_%u.log" % (event_set, event_type, int(time.time()))
                    self.logger.info(event_data)
                                
        except Exception as error:
            print("DraftStartSearchV2 Error: %s" % error)
            
    #Wrapper function for performing a search based on the draft type
    def DraftDataSearch(self):
        #if self.draft_set == None:
        #    self.ClearDraft(False)
        #self.DraftStartSearch()
        
        if self.draft_type == LIMITED_TYPE_DRAFT_PREMIER_V1:
            if len(self.initial_pack[0]) == 0:
                self.DraftPackSearchPremierP1P1()
            self.DraftPackSearchPremierV1()
            self.DraftPickedSearchPremierV1()
        elif self.draft_type == LIMITED_TYPE_DRAFT_PREMIER_V2:
            if len(self.initial_pack[0]) == 0:
                self.DraftPackSearchPremierP1P1()
            self.DraftPackSearchPremierV2()
            self.DraftPickedSearchPremierV2() 
        elif self.draft_type == LIMITED_TYPE_DRAFT_QUICK:
            self.DraftPackSearchQuick()
            self.DraftPickedSearchQuick()
        elif self.draft_type == LIMITED_TYPE_DRAFT_TRADITIONAL:
            if len(self.initial_pack[0]) == 0:
                self.DraftPackSearchTraditionalP1P1()
            self.DraftPackSearchTraditional()
            self.DraftPickedSearchTraditional()
        elif (self.draft_type == LIMITED_TYPE_SEALED) or (self.draft_type == LIMITED_TYPE_SEALED_TRADITIONAL):
            self.SealedPackSearch()
        return
        
    def DraftPackSearchPremierP1P1(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "CardsInPack"
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        #Remove any prefix (e.g. log timestamp)
                        start_offset = line.find("{\"id\":")                       
                        self.logger.info(line)
                        draft_data = json.loads(line[start_offset:])
                        request_data = draft_data["request"]
                        payload_data = json.loads(request_data)["Payload"]
                        
                        pack_cards = []
                        try:

                            card_data = json.loads(payload_data)
                            cards = card_data["CardsInPack"]

                            for card in cards:
                                pack_cards.append(str(card))
                            
                            pack = card_data["PackNumber"]
                            pick = card_data["PickNumber"]
                            
                            pack_index = (pick - 1) % 8
                            
                            if self.current_pack != pack:
                                self.initial_pack = [[]] * 8
                        
                            if len(self.initial_pack[pack_index]) == 0:
                                self.initial_pack[pack_index] = pack_cards
                                
                            self.pack_cards[pack_index] = pack_cards
                                
                            if (self.current_pack == 0) and (self.current_pick == 0):
                                self.current_pack = pack
                                self.current_pick = pick
                            
                            if(self.step_through):
                                break
        
                        except Exception as error:
                            error_string = "DraftPackSearchPremierP1P1 Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
            if log.closed == False:
                log.close() 
        except Exception as error:
            error_string = "DraftPackSearchPremierP1P1 Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        
        return pack_cards
    def DraftPickedSearchPremierV1(self):
        offset = self.pick_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]==> Event_PlayerDraftMakePick "
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pick_offset = offset
                        start_offset = line.find("{\"id\"")
                        self.logger.info(line)

                        try:
                            #Identify the pack
                            draft_data = json.loads(line[start_offset:])
                            
                            request_data = json.loads(draft_data["request"])
                            param_data = json.loads(request_data["Payload"])
                            
                            pack = int(param_data["Pack"])
                            pick = int(param_data["Pick"])
                            card = str(param_data["GrpId"])
                            
                            pack_index = (pick - 1) % 8
                            
                            if self.previous_picked_pack != pack:
                                self.picked_cards = [[] for i in range(8)]
                            
                            self.picked_cards[pack_index].append(card)
                            self.taken_cards.append(card)
                            
                            self.previous_picked_pack = pack
                            self.current_picked_pick = pick
                            
                            if self.step_through:
                                break; 
                            
                        except Exception as error:
                            error_string = "DraftPickedSearchPremierV1 Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)         
        except Exception as error:
            error_string = "DraftPickedSearchPremierV1 Error: %s" % error
            print(error_string)
            self.logger.info(error_string)

        
    def DraftPackSearchPremierV1(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]Draft.Notify "
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pack_offset = offset
                        start_offset = line.find("{\"draftId\"")
                        self.logger.info(line)
                        pack_cards = []
                        #Identify the pack
                        draft_data = json.loads(line[start_offset:])
                        try:
                                
                            cards = draft_data["PackCards"].split(',') 
                                
                            for card in cards:
                                pack_cards.append(str(card))
                                        
                            pack = draft_data["SelfPack"]
                            pick = draft_data["SelfPick"]
                                
                            pack_index = (pick - 1) % 8
                            
                            if self.current_pack != pack:
                                self.initial_pack = [[]] * 8
                        
                            if len(self.initial_pack[pack_index]) == 0:
                                self.initial_pack[pack_index] = pack_cards
                                
                            self.pack_cards[pack_index] = pack_cards
                            
                            self.current_pack = pack
                            self.current_pick = pick
                            
                            if(self.step_through):
                                break
    
                        except Exception as error:
                            error_string = "DraftPackSearchPremierV1 Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
             
        except Exception as error:
            error_string = "DraftPackSearchPremierV1 Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        return pack_cards
        
    def DraftPackSearchPremierV2(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]Draft.Notify "
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pack_offset = offset
                        self.logger.info(line)
                        pack_cards = []
                        #Identify the pack
                        draft_data = json.loads(line[len(draft_string):])
                        try:

                            cards = draft_data["PackCards"].split(',') 
                                
                            for card in cards:
                                pack_cards.append(str(card))
                                        
                            pack = draft_data["SelfPack"]
                            pick = draft_data["SelfPick"]
                                
                            pack_index = (pick - 1) % 8
                            
                            if self.current_pack != pack:
                                self.initial_pack = [[]] * 8
                        
                            if len(self.initial_pack[pack_index]) == 0:
                                self.initial_pack[pack_index] = pack_cards
                                
                            self.pack_cards[pack_index] = pack_cards
                            
                            self.current_pack = pack
                            self.current_pick = pick
                            
                            if(self.step_through):
                                break
    
                        except Exception as error:
                            error_string = "DraftPackSearchPremierV2 Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
             
        except Exception as error:
            error_string = "DraftPackSearchPremierV2 Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        return pack_cards

    
    def DraftPickedSearchPremierV2(self):
        offset = self.pick_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]==> Draft.MakeHumanDraftPick "
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        #print(line)
                        self.logger.info(line)
                        self.pick_offset = offset
                        try:
                            #Identify the pack
                            draft_data = json.loads(line[len(draft_string):])
                            
                            request_data = json.loads(draft_data["request"])
                            param_data = request_data["params"]
                            
                            pack = int(param_data["packNumber"])
                            pick = int(param_data["pickNumber"])
                            card = param_data["cardId"]
                            
                            pack_index = (pick - 1) % 8
                            
                            if self.previous_picked_pack != pack:
                                self.picked_cards = [[] for i in range(8)]
                                 
                            self.picked_cards[pack_index].append(card)
                            self.taken_cards.append(card)
                            
                            self.previous_picked_pack = pack
                            self.current_picked_pick = pick
    
                            
                            if self.step_through:
                                break; 
                            
                        except Exception as error:
                            error_string = "DraftPickedSearchPremierV2 Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
          
        except Exception as error:
            error_string = "DraftPickedSearchPremierV2 Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
    
    def DraftPackSearchQuick(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "DraftPack"
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pack_offset = offset
                        #Remove any prefix (e.g. log timestamp)
                        start_offset = line.find("{\"CurrentModule\"")                       
                        self.logger.info(line)
                        draft_data = json.loads(line[start_offset:])
                        payload_data = json.loads(draft_data["Payload"])
                        pack_data = payload_data["DraftPack"]
                        draft_status = payload_data["DraftStatus"]
                        
                        if draft_status == "PickNext":
                            pack_cards = []
                            try:

                                cards = pack_data
                                
                                for card in cards:
                                    pack_cards.append(str(card))
                                            
                                pack = payload_data["PackNumber"] + 1
                                pick = payload_data["PickNumber"] + 1  
                                pack_index = (pick - 1) % 8
                                
                                if self.current_pack != pack:
                                    self.initial_pack = [[]] * 8
                            
                                if len(self.initial_pack[pack_index]) == 0:
                                    self.initial_pack[pack_index] = pack_cards
                                    
                                self.pack_cards[pack_index] = pack_cards
                                    
                                self.current_pack = pack
                                self.current_pick = pick
                                
                                if(self.step_through):
                                    break
        
                            except Exception as error:
                                error_string = "DraftPackSearchQuick Sub Error: %s" % error
                                print(error_string)
                                self.logger.info(error_string)
            if log.closed == False:
                log.close() 
        except Exception as error:
            error_string = "DraftPackSearchQuick Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        
        return pack_cards
        
    def DraftPickedSearchQuick(self):
        offset = self.pick_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]==> BotDraft_DraftPick "
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.logger.info(line)
                        self.pick_offset = offset
                        try:
                            #Identify the pack
                            draft_data = json.loads(line[string_offset+len(draft_string):])
                            
                            request_data = json.loads(draft_data["request"])
                            payload_data = json.loads(request_data["Payload"])
                            print("payload_data: %s" % str(payload_data))
                            pick_data = payload_data["PickInfo"]
                            print("pick_data: %s" % str(pick_data))
                            
                            pack = pick_data["PackNumber"] + 1
                            pick = pick_data["PickNumber"] + 1
                            card = pick_data["CardId"]
                            
                            pack_index = (pick - 1) % 8
                            
                            if self.previous_picked_pack != pack:
                                self.picked_cards = [[] for i in range(8)]
                                 
                            self.previous_picked_pack = pack
                            self.current_picked_pick = pick
                            
                            self.picked_cards[pack_index].append(card)
                            self.taken_cards.append(card)
    
                            if self.step_through:
                                break
                            
                        except Exception as error:
                            error_string = "DraftPickedSearchQuick Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
            if log.closed == False:
                log.close()      
        except Exception as error:
            error_string = "DraftPickedSearchQuick Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
            
    def DraftPackSearchTraditionalP1P1(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "CardsInPack"
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        #Remove any prefix (e.g. log timestamp)
                        start_offset = line.find("{\"id\":")                       
                        self.logger.info(line)
                        draft_data = json.loads(line[start_offset:])
                        request_data = draft_data["request"]
                        payload_data = json.loads(request_data)["Payload"]
                        
                        pack_cards = []
                        try:

                            card_data = json.loads(payload_data)
                            cards = card_data["CardsInPack"]

                            for card in cards:
                                pack_cards.append(str(card))
                            
                            pack = card_data["PackNumber"]
                            pick = card_data["PickNumber"]
                            
                            pack_index = (pick - 1) % 8
                            
                            if self.current_pack != pack:
                                self.initial_pack = [[]] * 8
                        
                            if len(self.initial_pack[pack_index]) == 0:
                                self.initial_pack[pack_index] = pack_cards
                                
                            self.pack_cards[pack_index] = pack_cards
                                
                            if (self.current_pack == 0) and (self.current_pick == 0):
                                self.current_pack = pack
                                self.current_pick = pick
                            
                            if(self.step_through):
                                break
        
                        except Exception as error:
                            error_string = "DraftPackSearchTraditionalP1P1 Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
            if log.closed == False:
                log.close() 
        except Exception as error:
            error_string = "DraftPackSearchTraditionalP1P1 Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        
        return pack_cards
        
    def DraftPickedSearchTraditional(self):
        offset = self.pick_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]==> Event_PlayerDraftMakePick "
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pick_offset = offset
                        start_offset = line.find("{\"id\"")
                        self.logger.info(line)

                        try:
                            #Identify the pack
                            draft_data = json.loads(line[start_offset:])
                            
                            request_data = json.loads(draft_data["request"])
                            param_data = json.loads(request_data["Payload"])
                            
                            pack = int(param_data["Pack"])
                            pick = int(param_data["Pick"])
                            card = str(param_data["GrpId"])
                            
                            pack_index = (pick - 1) % 8
                            
                            if self.previous_picked_pack != pack:
                                self.picked_cards = [[] for i in range(8)]
                            
                            self.picked_cards[pack_index].append(card)
                            self.taken_cards.append(card)
                            
                            self.previous_picked_pack = pack
                            self.current_picked_pick = pick
                            
                            if self.step_through:
                                break; 
                            
                        except Exception as error:
                            error_string = "DraftPickedSearchPremierV1 Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)         
        except Exception as error:
            error_string = "DraftPickedSearchTraditional Error: %s" % error
            print(error_string)
            self.logger.info(error_string)

        
    def DraftPackSearchTraditional(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "[UnityCrossThreadLogger]Draft.Notify "
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pack_offset = offset
                        start_offset = line.find("{\"draftId\"")
                        self.logger.info(line)
                        pack_cards = []
                        #Identify the pack
                        draft_data = json.loads(line[start_offset:])
                        try:
                                
                            cards = draft_data["PackCards"].split(',') 
                                
                            for card in cards:
                                pack_cards.append(str(card))
                                        
                            pack = draft_data["SelfPack"]
                            pick = draft_data["SelfPick"]
                                
                            pack_index = (pick - 1) % 8
                            
                            if self.current_pack != pack:
                                self.initial_pack = [[]] * 8
                        
                            if len(self.initial_pack[pack_index]) == 0:
                                self.initial_pack[pack_index] = pack_cards
                                
                            self.pack_cards[pack_index] = pack_cards
                            
                            self.current_pack = pack
                            self.current_pick = pick
                            
                            if(self.step_through):
                                break
    
                        except Exception as error:
                            error_string = "DraftPackSearchTraditional Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
             
        except Exception as error:
            error_string = "DraftPackSearchTraditional Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        return pack_cards

    def SealedPackSearch(self):
        offset = self.pack_offset
        draft_data = object()
        draft_string = "EventGrantCardPool"
        pack_cards = []
        pack = 0
        pick = 0
        #Identify and print out the log lines that contain the draft packs
        try:
            with open(self.arena_file, 'r') as log:
                log.seek(offset)

                while(True):
                    line = log.readline()
                    if not line:
                        break
                    offset = log.tell()
                    
                    string_offset = line.find(draft_string)
                    
                    if string_offset != -1:
                        self.pack_offset = offset
                        start_offset = line.find("{\"CurrentModule\"")
                        self.logger.info(line)
                        #Identify the pack
                        draft_data = json.loads(line[start_offset:])
                        payload_data = json.loads(draft_data["Payload"])
                        changes = payload_data["Changes"]
                        try:
                            for change in changes:
                                if change["Source"] == "EventGrantCardPool":
                                    card_list_data = change["GrantedCards"]
                                    for card_data in card_list_data:
                                        card = str(card_data["GrpId"])
                                        self.taken_cards.append(card)
                                                   
                        except Exception as error:
                            error_string = "SealedPackSearch Sub Error: %s" % error
                            print(error_string)
                            self.logger.info(error_string)
             
        except Exception as error:
            error_string = "SealedPackSearch Error: %s" % error
            print(error_string)
            self.logger.info(error_string)
        return pack_cards
        
    def RetrieveDataSources(self):
        data_sources = OrderedDict()
        
        try:
            if self.draft_type != LIMITED_TYPE_UNKNOWN:
                draft_list = list(limited_types_dict.keys())
                draft_type = [x for x in draft_list if limited_types_dict[x] == self.draft_type][0]
                draft_list.insert(0, draft_list.pop(draft_list.index(draft_type)))
                
                #Search for the set files
                for type in draft_list:
                    file_name = "_".join((self.draft_set.upper(),type,SET_FILE_SUFFIX))
                    file = FE.SearchLocalFiles([os.getcwd()], [file_name])
                    if len(file):
                        result, json_data = FE.FileIntegrityCheck(file[0])
                        
                        if result == FE.Result.VALID:
                            data_sources[type] = file[0]
        
        except Exception as error:
            print("RetrieveDataSources Error: %s" % error)
    
        if len(data_sources) == 0:
            data_sources = DATA_SOURCES_NONE

        return data_sources
        
    def RetrieveTierSource(self):
        tier_source = ""
        
        try:
            if self.draft_set != None:
                file = FE.SearchLocalFiles([os.getcwd()], [TIER_FILE_PREFIX])
                
                if len(file):
                    tier_source = file[0]
        
        except Exception as error:
            print("RetrieveTierSource Error: %s" % error)

        return tier_source
        
    def RetrieveSetData(self, file):
        result = FE.Result.ERROR_MISSING_FILE
        self.set_data = None
        
        try:
            result, json_data = FE.FileIntegrityCheck(file)
            
            if result == FE.Result.VALID:
                self.set_data = json_data
        
        except Exception as error:
            print("RetrieveSetData Error: %s" % error)
            
        return result
        
    def RetrieveColorLimits(self, bayesian_enabled):
        deck_limits = {}
        
        try:
            upper_limit, lower_limit = CL.RatingsLimits(self.set_data["card_ratings"], bayesian_enabled)
            deck_limits ={"upper" : upper_limit, "lower" : lower_limit}
        except Exception as error:
            print("RetrieveColorLimits Error: %s" % error)
        return deck_limits
        
    def RetrieveColorWinRate(self):
        deck_colors = OrderedDict()
        for colors in DECK_FILTERS:
            deck_colors[colors] = colors
        
        try:
            if self.set_data:
                for colors in self.set_data["color_ratings"].keys():
                    for deck_color in deck_colors.keys():
                        if (len(deck_color) == len(colors)) and set(deck_color).issubset(colors):
                            ratings_string = deck_color + " (%s%%)" % (self.set_data["color_ratings"][colors])
                            deck_colors[deck_color] = ratings_string
        except Exception as error:
            print("RetrieveColorWinRate Error: %s" % error)
        return deck_colors
       
    def PickedCards(self, pack_index):
        picked_cards = []
        
        if self.set_data != None:
            if pack_index < len(self.picked_cards):
                for card in self.picked_cards[pack_index]:
                    try:
                        picked_cards.append(self.set_data["card_ratings"][card]["name"])
                    except Exception as error:
                        print("PickedCards Error: %s" % error)
            
        return picked_cards  

    def InitialPackCards(self, pack_index):
        pack_cards = []
        
        if self.set_data != None:
            if pack_index < len(self.initial_pack):
                for card in self.initial_pack[pack_index]:
                    try:
                        pack_cards.append(self.set_data["card_ratings"][card])
                    except Exception as error:
                        print("InitialPackCards Error: %s" % error)
        
        return pack_cards        
        
    def PackCards(self, pack_index):
        pack_cards = []
        
        if self.set_data != None:
            if pack_index < len(self.pack_cards):
                for card in self.pack_cards[pack_index]:
                    try:
                        pack_cards.append(self.set_data["card_ratings"][card])
                    except Exception as error:
                        print("PackCards Error: %s" % error)
        
        return pack_cards
        
    def TakenCards(self):
        taken_cards = []
        
        if self.set_data != None:
            for card in self.taken_cards:
                try:
                    taken_cards.append(self.set_data["card_ratings"][card])
                except Exception as error:
                    print("TakenCards Error: %s" % error)
        
        return taken_cards
        
    def RetrieveTierData(self, file, deck_colors):
        tier_data = {}
        try:
            if os.path.exists(file):
                with open(file, 'r') as json_file:
                    data = json.loads(json_file.read())
                    if data["meta"]["set"] == self.draft_set.upper():
                        tier_data = data
                        deck_colors["Tier"] = "Tier (%s)" % data["meta"]["label"]
             
        except Exception as error:
            print("RetrieveTierData Error: %s" % error)   
        return tier_data
#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Sibyl: A modular Python chat bot framework
# Copyright (c) 2015-2016 Joshua Haas <jahschwa.com>
#
# This file is part of Sibyl.
#
# Sibyl is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
################################################################################

import time,os,socket,copy,logging,inspect,traceback
from collections import OrderedDict as odict
import ConfigParser as cp

from sibyl.lib.protocol import Protocol
import sibyl.lib.util as util
from sibyl.lib.password import Password

DUMMY = 'dummy'

class DuplicateOptError(Exception):
  pass

################################################################################
# Config class                                                                 #
################################################################################

class Config(object):

  # indices in option tuple for convenience
  DEF = 0
  REQ = 1
  PARSE = 2
  VALID = 3
  POST = 4

  # config reload results
  FAIL = 0
  SUCCESS = 1
  ERRORS = 2
  DUPLICATES = 3

  def __init__(self,conf_file):
    """create a new config parser tied to the given bot"""

    # OrderedDict containing full descriptions of options
    self.OPTS = odict([

#option         default             requir  parse_func            validate_func       post_func
#----------------------------------------------------------------------------------------------
('protocols',   ({},                True,   self.parse_protocols, None,               None)), 
('enable',      ([],                False,  self.parse_plugins,   None,               None)),
('disable',     ([],                False,  self.parse_plugins,   None,               None)),
('cmd_dir',     ('cmds',            False,  None,                 self.valid_dir,     None)),
('rooms',       ({},                False,  self.parse_rooms,     None,               None)),
('nick_name',   ('Sibyl',           False,  None,                 None,               None)),
('log_level',   (logging.INFO,      False,  self.parse_log,       None,               None)),
('log_file',    ('data/sibyl.log',  False,  None,                 self.valid_wfile,   None)),
('log_append',  (True,              False,  self.parse_bool,      None,               None)),
('log_requests',(False,             False,  self.parse_bool,      None,               None)),
('log_urllib3', (False,             False,  self.parse_bool,      None,               None)),
('bw_list',     ([('w','*','*')],   False,  self.parse_bw,        self.valid_bw,      None)),
('chat_ctrl',   (False,             False,  self.parse_bool,      None,               None)),
('cmd_prefix',  (None,              False,  None,                 None,               None)),
('except_reply',(False,             False,  self.parse_bool,      None,               None)),
('only_direct', (True,              False,  self.parse_bool,      None,               None)),
('catch_except',(True,              False,  self.parse_bool,      None,               None)),
('help_plugin', (False,             False,  self.parse_bool,      None,               None)),
('recon_wait',  (60,                False,  self.parse_int,       None,               None)),
('kill_stdout', (True,              False,  self.parse_bool,      None,               None)),
('tell_errors', (True,              False,  self.parse_bool,      None,               None)),
('admin_protos',(['cli'],           False,  self.parse_admin,     self.valid_admin,   None))

    ])

    # create "namespace" dict
    self.NS = {k:'sibylbot' for k in self.OPTS}

    # initialise variables
    self.opts = None
    self.conf_file = conf_file
    self.log_msgs = []
    self.logging = logging

    # raise an exception if we can't write to conf_file
    util.can_write_file(self.conf_file,delete=True)

    # write a default conf_file if it doesn't exist at all
    if not os.path.isfile(self.conf_file):
      self.write_default_conf()

  # @param func (function) static function to bind to this object
  # @return (function) the parameter as a bound method
  def __bind(self,func):
    """bing the given function to self"""

    return func.__get__(self,Config)

  # @return (OrderedDict) defaults {option:value}
  def get_default(self):
    """return a dict of defaults in the form {opt:value}"""

    # populate a dictionary with the default values for all options
    opts = self.OPTS.iteritems()
    return odict([(opt,value[self.DEF]) for (opt,value) in opts])

  # @param opts (list of dict) options to add to defaults
  # @param ns (str) the namespace (e.g. filename) of the option
  # @return (bool) True if all opts added successfully
  def add_opts(self,opts,ns):
    """add several new options, catching exceptions"""

    success = True
    for opt in opts:
      try:
        self.add_opt(opt,ns)
      except DuplicateOptError:
        success = False

    return success

  # @param opt (dict) option to add to defaults
  # @param ns (str) the namespace (e.g. filename) of the option
  # @raise (DuplicateOptError) if the opt already exists
  #
  # See @botconf in https://github.com/TheSchwa/sibyl/wiki/Plug-Ins
  def add_opt(self,opt,ns):
    """add the option to our dictionary for parsing, log errors"""

    # construct option tuple and add to self.OPTS
    name = opt['name']

    if name in self.OPTS:
      self.log('critical','Duplicate opt "%s" from "%s" and "%s"' %
          (name,self.NS[name],ns))
      raise DuplicateOptError

    opt['default'] = opt.get('default',None)
    opt['req'] = opt.get('req',False)

    for hook in ('parse','valid','post'):
      opt[hook] = opt.get(hook,None)
      if opt[hook]:
        opt[hook] = self.__bind(opt[hook])

    self.OPTS[name] = (
      opt['default'],opt['req'],opt['parse'],opt['valid'],opt['post'])
    self.NS[name] = ns

  # @param opt (str) the option to set
  # @param val (str) the value to set (will be parsed into a Python object)
  # @return (bool) True if the option was actually changed
  def set_opt(self,opt,val):
    """parse,validate,set an opt in the bot returning False on failure"""

    # try to parse if necessary
    try:
      func = self.OPTS[opt][self.PARSE]
      if func:
        val = func(opt,val)
    except:
      return False

    # validate if necessary
    func = self.OPTS[opt][self.VALID]
    if func:
      if not func(val):
        return False

    # try to post if necessary
    try:
      func = self.OPTS[opt][self.POST]
      if func:
        val = func(self.opts,opt,val)
    except:
      return False

    # set the option in ourself
    self.opts[opt] = val
    return True

  # @param opt (str) the option to set
  # @param val (str) the value to set (will be parsed into a Python object)
  # @return (bool) True if the option was actually changed and saved
  def save_opt(self,opt,val,msg=None):
    """call set_opt then save it to the config file"""

    # return if set_opt() fails
    if not self.set_opt(opt,val):
      return False

    # note the time of the change at the end of the line
    s = ('### MODIFIED: '+time.asctime())
    if msg:
      s += (' ('+msg+')')
    s += ('\n'+opt+' = '+val+'\n')
    with open(self.conf_file,'r') as f:
      lines = f.readlines()

    # search the config file for the specified opt to replace
    start = -1
    for (i,line) in enumerate(lines):
      line = line.strip()
      if line.startswith(opt):
        start = i
        break

    # if the opt was not active in the config file, simply add it to the end
    if start==-1:
      lines.append(s)

    # if the opt existed in the file
    else:

      # delete all non-comments until reaching next opt (account for multiline)
      del lines[start]
      n = start
      while (n<len(lines)):
        line = lines[n].strip()
        if self.__is_opt_line(line):
          break
        elif line.startswith('#') or line.startswith(';') or len(line)==0:
          n += 1
        else:
          del lines[n]
      lines.insert(start,s)

      # check for and delete an existing "### MODIFIED" line
      if start>0 and lines[start-1].startswith('### MODIFIED: '):
        del lines[start-1]

    with open(self.conf_file,'w') as f:
      f.writelines(lines)
    return True

  # @param line (str) the line to check
  # @return (bool) True if the line contains an active (uncommented) option
  def __is_opt_line(self,line):
    """return True if this line contains an option"""

    line = line.strip()
    if line.startswith('#') or line.startswith(';'):
      return False

    set_char = line.find('=')
    com_char = line.find(' ;')
    if set_char==-1:
      return False
    if com_char==-1:
      return True
    return set_char<com_char

  # @return (int) the result of the reload
  #   SUCCESS - no errors or warnings of any kind
  #   ERRORS  - ignored sections, ignore opts, parse fails, or validate fails
  #   FAIL    - missing any required opts
  def reload(self,log=True):
    """load opts from config file and check for errors"""

    orig = self.logging
    self.logging = log

    # parse options from the config file and store them in self.opts
    self.__update()

    # record missing required options
    errors = []
    for opt in self.opts:
      if self.OPTS[opt][self.REQ] and not self.opts[opt]:
        self.log('critical','Missing required option "%s"' % opt)
        errors.append(opt)

    self.logging = orig

    # return status
    if len(errors):
      return self.FAIL

    warnings = [x for x in self.log_msgs if x[0]>=logging.WARNING]
    if len(warnings):
      return self.ERRORS
    else:
      return self.SUCCESS

  def __update(self):
    """update self.opts from config file"""

    # start with the defaults
    self.opts = self.get_default()

    # get the values in the config file
    opts = self.__read()
    self.__parse(opts)
    self.__validate(opts)

    # update self.opts with parsed and valid values
    self.opts.update(opts)

    # execute post hooks
    self.__post(self.opts)

  # @return (dict) the values of all config options read from the file
  def __read(self):
    """return a dict representing config file in the form {opt:value}"""

    # use a SafeConfigParser to read options from the config file
    config = cp.SafeConfigParser()
    try:
      config.readfp(FakeSecHead(open(self.conf_file)))
    except Exception as e:
      full = traceback.format_exc(e)
      short = full.split('\n')[-2]
      self.log('critical','Unable to read/parse config file')
      self.log('error','  %s' % short)
      self.log('debug',full)
      return {}

    # Sibyl config does not use sections; options in sections will be ignored
    secs = config.sections()
    for sec in secs:
      if sec!=DUMMY:
        self.log('error','Ignoring section "%s" in config file' % sec)

    # return a dictionary of all opts read from the config file
    items = config.items(DUMMY)
    return {x:y for (x,y) in items}

  # @param opts (dict) potential opt:value pairs to parse
  def __parse(self,opts):
    """parse the opt value strings into objects using their parse function"""

    for opt in opts.keys():

      # delete unrecognized options
      if opt not in self.OPTS:
        self.log('info','Unknown config option "%s"' % opt)
        del opts[opt]

      # parse recognized options and catch parsing exceptions
      else:
        func = self.OPTS[opt][self.PARSE]
        if func:
          try:
            opts[opt] = func(opt,opts[opt])
          except Exception as e:
            self.log('error','Error parsing "%s"; using default=%s' %
                (opt,self.opts[opt]))
            del opts[opt]

  # @param opts (dict) opt:value pairs to validate
  def __validate(self,opts):
    """delete opts that fail their validation function"""

    # delete invalid options
    for opt in opts.keys():
      func = self.OPTS[opt][self.VALID]
      if func and not func(opts[opt]):
        self.log('error','Invalid value for "%s"; using default=%s' %
            (opt,self.opts[opt]))
        del opts[opt]

  # @param opts (dict) opt:value pairs to run post triggers on
  def __post(self,opts):
    """allow opts to run code to check the values of other opts"""

    for opt in opts.keys():
      func = self.OPTS[opt][self.POST]
      if func:
        try:
          opts[opt] = func(opts,opt,opts[opt])
        except Exception as e:
          self.log('error','Error running post for "%s"; using default=%s' %
              (opt,self.opts[opt]))
          del opts[opt]

  def write_default_conf(self):
    """write a default, completely commented-out config file"""

    s = ''
    for (opt,val) in self.get_default().iteritems():
      s += ('#%s = %s\n' % (opt,val))
    with open(self.conf_file,'w') as f:
      f.write(s)

################################################################################
#                                                                              #
# Validate functions                                                           #
#                                                                              #
# @param foo (object) the object to validate                                   #
# @return (bool) True if the object is acceptable                              #
#                                                                              #
################################################################################

  def valid_ip(self,s):
    """return True if s is a valid ip"""

    # account for port
    if ':' in s:
      s = s.split(':')
      if len(s)>2:
        return False
      if not s[1].isdigit():
        return False
      s = s[0]

    # use socket library to decide if the IP is valid
    try:
      socket.inet_aton(s)
      return True
    except:
      return False

  def valid_rfile(self,s):
    """return True if we can read the file"""

    try:
      with open(s,'r') as f:
        return True
    except:
      return False

  def valid_wfile(self,s):
    """return True if we can write to the file"""

    try:
      util.can_write_file(s,delete=True)
      return True
    except:
      return False

  def valid_bw(self,bw):
    """return True if the bw list is valid"""

    # just check the color; everything else happens in parse_bw()
    for (color,_,_) in bw:
      if color not in ('b','w'):
        return False
    return True

  def valid_dir(self,cmd):
    """return True if the directory exists"""

    try:
      os.listdir(os.path.abspath(cmd))
      return True
    except:
      return False

  def valid_admin(self,protos):
    """return True if every protocol in the list exists"""

    for proto in protos:
      fname = os.path.join('protocols','sibyl_'+proto+os.path.extsep+'py')
      if not os.path.isfile(fname):
        return False

    return True

################################################################################
#                                                                              #
# Parse functions                                                              #
#                                                                              #
# @param opt (str) the name of the option being parsed                         #
# @param val (str) the string to parse into a Python object                    #
#                                                                              #
################################################################################

  # @return (dict of str:class) protocol names and classes to use
  def parse_protocols(self,opt,val):
    """parse the protocols and return the subclasses"""

    val = util.split_strip(val,',')
    protocols = {}
    success = False

    for proto in val:

      protocols[proto] = None
      fname = os.path.join('protocols','sibyl_'+proto+os.path.extsep+'py')
      if not os.path.isfile(fname):
        self.log('critical','No matching file in protocols/ for "%s"' % proto)
        continue

      try:
        mod = util.load_module('sibyl_'+proto,'protocols')
        for (name,clas) in inspect.getmembers(mod,inspect.isclass):
          if issubclass(clas,Protocol) and clas!=Protocol:
            protocols[proto] = clas
        if protocols[proto] is None:
          self.log('critical',
              'Protocol "%s" does not contain a lib.protocol.Protocol subclass' % proto)

      except Exception as e:
        full = traceback.format_exc(e)
        short = full.split('\n')[-2]
        self.log('critical','Exception importing protocols/%s:' % ('sibyl_'+proto))
        self.log('critical','  %s' % short)
        self.log('debug',full)

    if None in protocols.values():
      raise ValueError
    return protocols

  # @return (list) list of plugins to treat as admin
  def parse_admin(self,opt,val):
    """parse the list of protocols"""

    return util.split_strip(val,',')

  # @return (list) a list of plugins to disable
  def parse_plugins(self,opt,val):
    """parse the list of disabled or enables plugins"""

    # individiual plugins are separated by commas
    val = val.replace('\n','').replace(' ','')
    return val.split(',')

  # @return (dict) a room to join with keys [room, nick, pass]
  def parse_rooms(self,opt,val):
    """parse the rooms into a list"""

    val = val.replace('\n','')
    entries = util.split_strip(val,';')
    rooms = {}
    for entry in entries:
      if entry=='':
        continue
      params = util.split_strip(entry,',')
      if not params[0] or not params[1]:
        raise ValueError

      # check for optional arguments
      room = {'room':params[1],'nick':None,'pass':None}
      if len(params)>2 and params[2]:
        room['nick'] = params[2]
      if len(params)>3 and params[3]:
        room['pass'] = Password(params[3])
      
      # add room to dict
      if params[0] in rooms:
        rooms[params[0]].append(room)
      else:
        rooms[params[0]] = [room]
    return rooms

  # @return (int) a log level from the logging module
  def parse_log(self,opt,val):
    """parse the specified log level"""

    levels = {'critical' : logging.CRITICAL,
              'error'    : logging.ERROR,
              'warning'  : logging.WARNING,
              'info'     : logging.INFO,
              'debug'    : logging.DEBUG}
    
    return levels[val]

  # @return (list of tuple) the black/white list
  #   where each tuple contains 3 (str): (color,user,cmd)
  def parse_bw(self,opt,val):
    """parse and fully expand the bw_list"""

    val = val.replace('\n','')

    # semi-colons divide separate rules
    entries = util.split_strip(val,';')

    # we don't want to use modifier methods on the actual default object
    bw = copy.copy(self.OPTS[opt][self.DEF])
    for entry in entries:
      if entry=='':
        continue

      # spaces divide fields
      (color,users,cmds) = util.split_strip(entry)

      # commas allow for multiple items per field
      users = util.split_strip(users,',')
      cmds = util.split_strip(cmds,',')
      for user in users:
        for cmd in cmds:
          bw.append((color,user,cmd))
    return bw

  # @return (bool)
  def parse_bool(self,opt,val):
    """return a bool"""

    if val.strip().lower()=='true':
      return True
    if val.strip().lower()=='false':
      return False
    raise ValueError

  # @return (int)
  def parse_int(self,opt,val):
    """return an int"""

    return int(val)

################################################################################
# Logging                                                                      #
################################################################################

  # @param lvl (int) a human-readable log level (e.g. 'debug')
  # @param msg (str) the message to log
  def log(self,lvl,msg):
    """add the message to the queue"""

    if self.logging:
      self.log_msgs.append((lvl,msg))

  def process_log(self):
    """should only be called after logging has been initialised in the bot"""

    log = logging.getLogger('config')
    for (lvl,msg) in self.log_msgs:
      lvl = self.parse_log(None,lvl)
      log.log(lvl,msg)
    self.clear_log()

  def clear_log(self):
    """clear the log"""
    
    self.log_msgs = []

################################################################################
# FakeSecHead class                                                            #
################################################################################

# insert a dummy section header so SafeConfigParser is happy
class FakeSecHead(object):
    def __init__(self, fp):
        self.fp = fp
        self.sechead = '[%s]\n' % DUMMY
    def readline(self):
        if self.sechead:
            try: 
                return self.sechead
            finally: 
                self.sechead = None
        else: 
            return self.fp.readline()

#!/usr/bin/env python
# -*- coding: utf-8 -*-

import multiprocessing
import time

from alex.components.slu.da import DialogueActItem, DialogueActConfusionNetwork
from alex.components.hub.messages import Command, SLUHyp, DMDA
from alex.components.dm.common import dm_factory, get_dm_type
from alex.components.dm.exceptions import DMException
from alex.utils.procname import set_proc_name


class DM(multiprocessing.Process):
    """DM accepts N-best list hypothesis or a confusion network generated by an SLU component.
    The result of this component is an output dialogue act.

    When the component receives an SLU hypothesis then it immediately responds with an dialogue act.

    This component is a wrapper around multiple dialogue managers which handles multiprocessing
    communication.
    """

    def __init__(self, cfg, commands, slu_hypotheses_in, dialogue_act_out, close_event):
        multiprocessing.Process.__init__(self)

        self.cfg = cfg
        self.commands = commands
        self.slu_hypotheses_in = slu_hypotheses_in
        self.dialogue_act_out = dialogue_act_out
        self.close_event = close_event
        self.last_user_da_time = time.time()
        self.last_user_diff_time = time.time()

        dm_type = get_dm_type(cfg)
        self.dm = dm_factory(dm_type, cfg)
        self.dm.new_dialogue()

    def process_pending_commands(self):
        """Process all pending commands.

        Available commands:
          stop() - stop processing and exit the process
          flush() - flush input buffers.
            Now it only flushes the input connection.

        Return True if the process should terminate.
        """

        while self.commands.poll():
            command = self.commands.recv()
            if self.cfg['DM']['debug']:
                self.cfg['Logging']['system_logger'].debug(command)

            if isinstance(command, Command):
                if command.parsed['__name__'] == 'stop':
                    return True

                if command.parsed['__name__'] == 'flush':
                    # discard all data in in input buffers
                    while self.slu_hypotheses_in.poll():
                        data_in = self.slu_hypotheses_in.recv()

                    self.dm.end_dialogue()

                    self.commands.send(Command("flushed()", 'DM', 'HUB'))
                    
                    return False

                if command.parsed['__name__'] == 'new_dialogue':
                    self.dm.new_dialogue()

                    self.cfg['Logging']['session_logger'].turn("system")
                    self.dm.log_state()

                    # I should generate the first DM output
                    da = self.dm.da_out()

                    if self.cfg['DM']['debug']:
                        s = []
                        s.append("DM Output")
                        s.append("-"*60)
                        s.append(unicode(da))
                        s.append("")
                        s = '\n'.join(s)
                        self.cfg['Logging']['system_logger'].debug(s)

                    self.cfg['Logging']['session_logger'].dialogue_act("system", da)

                    self.commands.send(DMDA(da, 'DM', 'HUB'))

                    return False

                if command.parsed['__name__'] == 'end_dialogue':
                    self.dm.end_dialogue()
                    return False

                if command.parsed['__name__'] == 'timeout':
                    # check whether there is a looong silence
                    # if yes then inform the DM

                    silence_time = command.parsed['silence_time']
                    cn = DialogueActConfusionNetwork()
                    cn.add(1.0, DialogueActItem('silence','time', silence_time))

                    self.dm.da_in(cn)
                    da = self.dm.da_out()

                    if self.cfg['DM']['debug']:
                        s = []
                        s.append("DM Output")
                        s.append("-"*60)
                        s.append(unicode(da))
                        s.append("")
                        s = '\n'.join(s)
                        self.cfg['Logging']['system_logger'].debug(s)

                    self.cfg['Logging']['session_logger'].turn("system")
                    self.cfg['Logging']['session_logger'].dialogue_act("system", da)

                    self.commands.send(DMDA(da, 'DM', 'HUB'))

                    if da.has_dat("bye"):
                        self.commands.send(Command('hangup()', 'DM', 'HUB'))

                    return False

        return False

    def read_slu_hypotheses_write_dialogue_act(self):
        # read SLU hypothesis
        if self.slu_hypotheses_in.poll():
            # read SLU hypothesis
            data_slu = self.slu_hypotheses_in.recv()

            if isinstance(data_slu, SLUHyp):
                # reset measuring of the user silence
                self.last_user_da_time = time.time()
                self.last_user_diff_time = time.time()

                # process the input DA
                self.dm.da_in(data_slu.hyp, utterance=data_slu.asr_hyp)

                self.cfg['Logging']['session_logger'].turn("system")
                self.dm.log_state()

                da = self.dm.da_out()

                if self.cfg['DM']['debug']:
                    s = []
                    s.append("DM Output")
                    s.append("-"*60)
                    s.append(unicode(da))
                    s.append("")
                    s = '\n'.join(s)
                    self.cfg['Logging']['system_logger'].debug(s)

                self.cfg['Logging']['session_logger'].dialogue_act("system", da)

                # do not communicate directly with the NLG, let the HUB decide
                # to do work. The generation of the output must by synchronised with the input.
                self.commands.send(DMDA(da, 'DM', 'HUB'))

                if da.has_dat("bye"):
                    self.commands.send(Command('hangup()', 'DM', 'HUB'))

            elif isinstance(data_slu, Command):
                self.cfg['Logging']['system_logger'].info(data_slu)
            else:
                raise DMException('Unsupported input.')

    def run(self):
        try:
            set_proc_name("alex_DM")

            while 1:
                # Check the close event.
                if self.close_event.is_set():
                    return

                time.sleep(self.cfg['Hub']['main_loop_sleep_time'])

                # process all pending commands
                if self.process_pending_commands():
                    return

                # process the incoming SLU hypothesis
                self.read_slu_hypotheses_write_dialogue_act()
        except:
            self.cfg['Logging']['system_logger'].exception('Uncaught exception in the DM process.')
            self.close_event.set()
            raise


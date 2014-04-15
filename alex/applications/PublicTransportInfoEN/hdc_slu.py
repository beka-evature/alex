#!/usr/bin/env python
# encoding: utf8
# This code is PEP8-compliant. See http://www.python.org/dev/peps/pep-0008.

from __future__ import unicode_literals

import copy

from alex.components.asr.utterance import Utterance, UtteranceHyp
from alex.components.slu.base import SLUInterface
from alex.components.slu.da import DialogueActItem, DialogueActConfusionNetwork

# if there is a change in search parameters from_stop, to_stop, time, then
# reset alternatives


def any_word_in(utterance, words):
    words = words if not isinstance(words, basestring) else words.strip().split()
    for alt_expr in words:
        if  alt_expr in utterance.utterance:
            return True

    return False


def all_words_in(utterance, words):
    words = words if not isinstance(words, basestring) else words.strip().split()
    for alt_expr in words:
        if  alt_expr not in utterance.utterance:
            return False
    return True


def phrase_in(utterance, words):
    return phrase_pos(utterance, words) != -1


def phrase_pos(utterance, words):
    """Returns the position of the given phrase in the given utterance, or -1 if not found.

    :rtype: int
    """
    utterance = utterance if not isinstance(utterance, list) else Utterance(' '.join(utterance))
    words = words if not isinstance(words, basestring) else words.strip().split()
    return utterance.find(words)

def first_phrase_span(utterance, phrases):
    """Returns the span (start, end+1) of the first phrase from the given list
    that is found in the utterance. Returns (-1, -1) if no phrase is found.

    :param utterance: The utterance to search in
    :param phrases: a list of phrases to be tried (in the given order)
    :rtype: tuple
    """
    for phrase in phrases:
        pos = phrase_pos(utterance, phrase)
        if pos != -1:
            return pos, pos + len(phrase)
    return -1, -1


def any_phrase_in(utterance, phrases):
    return first_phrase_span(utterance, phrases) != (-1, -1)


class PTICSHDCSLU(SLUInterface):
    def __init__(self, preprocessing, cfg=None):
        super(PTICSHDCSLU, self).__init__(preprocessing, cfg)
        self.cldb = self.preprocessing.cldb

    def abstract_utterance(self, utterance):
        """
        Return a list of possible abstractions of the utterance.

        :param utterance: an Utterance instance
        :return: a list of abstracted utterance, form, value, category label tuples
        """

        abs_utts = copy.deepcopy(utterance)
        category_labels = set()

        start = 0
        while start < len(utterance):
            end = len(utterance)
            while end > start:
                f = tuple(utterance[start:end])
                #print start, end
                #print f

                if f in self.cldb.form2value2cl:
                    for v in self.cldb.form2value2cl[f]:
                        for c in self.cldb.form2value2cl[f][v]:
                            abs_utts = abs_utts.replace(f, (c.upper() + '='+v,))

                            category_labels.add(c.upper())
                            break
                        else:
                            continue

                        break

                    #print f

                    # skip all substring for this form
                    start = end
                    break
                end -= 1
            else:
                start += 1


        return abs_utts, category_labels

    def __repr__(self):
        return "PTICSHDCSLU({preprocessing}, {cfg})".format(preprocessing=self.preprocessing, cfg=self.cfg)

    def parse_stop(self, abutterance, cn):
        """ Detects stops in the input abstract utterance.

        :param abutterance: the input abstract utterance.
        :param cn: The output dialogue act item confusion network.
        """

        # regular parsing
        phr_wp_types = [('from', set(['from', 'at', 'begining', 'start', 'starting', 'origin', # of, off
                                      'originated', 'originating', 'origination', 'initial'])),
                        ('to', set(['to', 'into', 'end', 'ending', 'terminal', 'final',
                                    'target', 'output', 'exit'])),
                        ('via', set(['via', 'through', 'transfer', 'interchange' ]))] # change line

        self.parse_waypoint(abutterance, cn, 'STOP=', 'stop', phr_wp_types)

    def parse_city(self, abutterance, cn):
        """ Detects stops in the input abstract utterance.

        :param abutterance: the input abstract utterance.
        :param cn: The output dialogue act item confusion network.
        """

        # regular parsing
        phr_wp_types = [('from', set(['from', 'begining', 'start', 'starting', 'origin', # of, off
                                      'originated', 'originating', 'origination', 'initial'])), # I'm at, I'm in ?
                        ('to', set(['to', 'into', 'end', 'ending', 'terminal', 'final',
                                    'target', 'output', 'exit'])),
                        ('via', set(['via', 'through', 'transfer', 'interchange' ])),
                        ('in', set(['for', 'after'])), # ? ['pro', 'po']
                       ]

        self.parse_waypoint(abutterance, cn, 'CITY=', 'city', phr_wp_types, phr_in=['in', 'at'])

    def parse_waypoint(self, abutterance, cn, wp_id, wp_slot_suffix, phr_wp_types, phr_in=None):
        """Detects stops or cities in the input abstract utterance
        (called through parse_city or parse_stop).

        :param abutterance: the input abstract utterance.
        :param cn: The output dialogue act item confusion network.
        """
        u = abutterance
        N = len(u)

        # simple "not" cannot be included as it collides with negation. "I do not want [,] go from Brooklin"
        phr_dai_types = [('confirm', set(['it departs', 'departs from', 'depart from', 'leave', 'leaves',
                                          'is the starting']), set()),
                         ('deny',
                          set(['not from', 'not at', 'not in', 'not on', 'not to', 'not into', 'and not',
                               'not the', 'rather than']), # don't, doesn't?
                          set(['not at all' 'not wish', 'not this way', 'no not that', 'not need help',
                               'not want', ]))]
        last_wp_pos = 0

        for i, w in enumerate(u):
            if w.startswith(wp_id):
                wp_name = w[len(wp_id):]
                wp_types = set()
                dai_type = 'inform'

                # test short preceding context to find the stop type (from, to, via)
                wp_precontext = {}
                for cur_wp_type, phrases in phr_wp_types:
                    wp_precontext[cur_wp_type] = first_phrase_span(u[max(last_wp_pos, i - 5):i], phrases)
                wp_types |= self._get_closest_wp_type(wp_precontext)
                # test short following context (0 = from, 1 = to, 2 = via)
                if not wp_types:
                    if any_phrase_in(u[i:i + 3], phr_wp_types[0][1] | phr_wp_types[2][1]):
                        wp_types.add('to')
                    elif any_phrase_in(u[i:i + 3], phr_wp_types[1][1]):
                        wp_types.add('from')
                # resolve context according to further preceding/following waypoint name (assuming from-to)
                if not wp_types:
                    if i >= 1 and u[i - 1].startswith(wp_id):
                        wp_types.add('to')
                    elif i <= N - 2 and u[i + 1].startswith(wp_id):
                        wp_types.add('from')
                # using 'in' slot if the previous checks did not work and we have phrases for 'in'
                if not wp_types and phr_in is not None and any_phrase_in(u[max(last_wp_pos, i - 5): i], phr_in):
                    wp_types.add('in')

                # test utterance type
                for cur_dai_type, phrases_pos, phrases_neg in phr_dai_types:
                    if any_phrase_in(u[last_wp_pos:i], phrases_pos) and not any_phrase_in(u[last_wp_pos:i], phrases_neg):
                        dai_type = cur_dai_type
                        break

                # add waypoint to confusion network (standard case: just single type is decided)
                if len(wp_types) == 1:
                    cn.add(1.0, DialogueActItem(dai_type, wp_types.pop() + '_' + wp_slot_suffix, wp_name))
                # backoff 1: add both 'from' and 'to' waypoint slots
                elif 'from' in wp_types and 'to' in wp_types:
                    cn.add(0.501, DialogueActItem(dai_type, 'from_' + wp_slot_suffix, wp_name))
                    cn.add(0.499, DialogueActItem(dai_type, 'to_' + wp_slot_suffix, wp_name))
                # backoff 2: let the DM decide in context resolution
                else:
                    cn.add(1.0, DialogueActItem(dai_type, '', wp_name))

                last_wp_pos = i + 1

    def _get_closest_wp_type(self, wp_precontext):
        """Finds the waypoint type that goes last in the context (if same end points are
        encountered, the type with a longer span wins).

        :param wp_precontext: Dictionary waypoint type -> span (start, end+1) in the preceding \
            context of the waypoint mention
        :returns: one-member set with the best type (if there is one with non-negative position), \
            or empty set on failure
        :rtype: set
        """
        best_type = None
        best_pos = (-2, -1)
        for cur_type, cur_pos in wp_precontext.iteritems():
            if cur_pos[1] > best_pos[1] or cur_pos[1] == best_pos[1] and cur_pos[0] < best_pos[0]:
                best_type = cur_type
                best_pos = cur_pos
        if best_type is not None:
            return set([best_type])
        return set()

    def parse_time(self, abutterance, cn):
        """Detects the time in the input abstract utterance.

        :param abutterance:
        :param cn:
        """

        u = abutterance

        preps_abs = set(["at", "time", "past", "after", "between", "before", "in"])
        preps_rel = set(["in", ])

        test_context = [('confirm', 'departure',
                         ['it leaves', 'it departures', 'it starts', 'is starting', 'is leaving', 'is departuring',
                          'departure point'],
                         []),
                        ('confirm', 'arrival',
                         ['it arrives', 'is arriving', 'will arrive', 'is coming', 'it comes', 'will come',
                          'arrival is'], # will reach
                         []),
                        ('confirm', '',
                         ['it is', 'you think', 'positive'],
                         []),
                        ('deny', 'departure',
                         ['not leaving', 'not leave', 'not departuring', 'not departure', 'not starting',
                          'not start', 'not want to go from'],
                         []),
                        ('deny', 'arrival',
                         ['not arriving', 'not arrive', 'not come', 'not comming', 'not want to arrive',
                          'not want to come', 'not want to go to', 'not want to arrive'],
                         []),
                        ('deny', '',
                         ['no', 'not want', 'negative'],
                         []),
                        ('inform', 'departure',
                         ['TASK=find_connection', 'departure', 'departing', 'depatrs', 'departs from', 'leaving',
                          'leaves', 'starts', 'starting', 'goes', 'would go', 'will go', 'VEHICLE=tram',
                          'want to go', 'want to leave',],
                         ['arrival', 'arrive', 'get to', 'to get', 'arriving', 'want to be at']),
                        ('inform', 'arrival',
                         ['arrival', 'arrive', 'get to', 'to get', 'arriving', 'want to be at'],
                         []),
                        ('inform', '',
                         [],
                         []),
        ]

        count_times = 0
        for i, w in enumerate(u):
            if w.startswith("TIME="):
                count_times += 1

        last_time_type = ''
        last_time = 0

        for i, w in enumerate(u):
            if w.startswith("TIME="):
                value = w[5:]
                time_abs = False
                time_rel = False

                if i >= 1:
                    if u[i - 1] in preps_abs:
                        time_abs = True
                    if u[i - 1] in preps_rel:
                        time_rel = True

                if count_times > 1:
                    j, k = last_time, i
                else:
                    j, k = 0, len(u)

                if value == "now" and not any_phrase_in(u[j:k], ['so what', 'what is the time',
                                                                 'can not hear', 'no longer telling me']):
                    time_rel = True

                if time_abs or time_rel:
                    for act_type, time_type, phrases_pos, phrases_neg in test_context:
                        if any_phrase_in(u[j:k], phrases_pos) and not any_phrase_in(u, phrases_neg):
                            break

                    if count_times > 1 and not time_type:
                        # use the previous type if there was time before this one
                        time_type = last_time_type

                    last_time_type = time_type

                    slot = (time_type + ('_time_rel' if time_rel else '_time')).lstrip('_')
                    cn.add(1.0, DialogueActItem(act_type, slot, value))

                last_time = i + 1

    def parse_date_rel(self, abutterance, cn):
        """Detects the relative date in the input abstract utterance.

        :param abutterance:
        :param cn:
        """

        u = abutterance

        confirm = phrase_in(u, ['it', 'does'])
        deny = phrase_in(u, ['not', 'want'])

        for i, w in enumerate(u):
            if w.startswith("DATE_REL="):
                value = w[9:]

                if confirm:
                    cn.add(1.0, DialogueActItem("confirm", 'date_rel', value))
                elif deny:
                    cn.add(1.0, DialogueActItem("deny", 'date_rel', value))
                else:
                    cn.add(1.0, DialogueActItem("inform", 'date_rel', value))

    def parse_ampm(self, abutterance, cn):
        """Detects the ampm in the input abstract utterance.

        :param abutterance:
        :param cn:
        """

        u = abutterance

        confirm = phrase_in(u, ['it', 'does'])
        deny = phrase_in(u, ['not', 'want'])

        for i, w in enumerate(u):
            if w.startswith("AMPM="):
                value = w[5:]

                if not (phrase_in(u, 'good night')):
                    if confirm:
                        cn.add(1.0, DialogueActItem("confirm", 'ampm', value))
                    elif deny:
                        cn.add(1.0, DialogueActItem("deny", 'ampm', value))
                    else:
                        cn.add(1.0, DialogueActItem("inform", 'ampm', value))

    def parse_vehicle(self, abutterance, cn):
        """Detects the vehicle (transport type) in the input abstract utterance.

        :param abutterance:
        :param cn:
        """

        u = abutterance

        confirm = phrase_in(u, ['it', 'does'])
        deny = phrase_in(u, ['not', 'want'])

        for i, w in enumerate(u):
            if w.startswith("VEHICLE="):
                value = w[8:]

                if confirm:
                    cn.add(1.0, DialogueActItem("confirm", 'vehicle', value))
                elif deny:
                    cn.add(1.0, DialogueActItem("deny", 'vehicle', value))
                else:
                    cn.add(1.0, DialogueActItem("inform", 'vehicle', value))

    def parse_task(self, abutterance, cn):
        """Detects the task in the input abstract utterance.

        :param abutterance:
        :param cn:
        """

        u = abutterance

        deny = phrase_in(u, ['not want', 'don\'t want', 'not looking for'])

        for i, w in enumerate(u):
            if w.startswith("TASK="):
                value = w[5:]

                if deny:
                    cn.add(1.0, DialogueActItem("deny", 'task', value))
                else:
                    cn.add(1.0, DialogueActItem("inform", 'task', value))

    def parse_non_speech_events(self, utterance, cn):
        """
        Processes non-speech events in the input utterance.

        :param utterance:
        :param cn:
        :return: None
        """
        u = utterance

        if  len(u.utterance) == 0 or "_silence_" == u or "__silence__" == u or "_sil_" == u:
            cn.add(1.0, DialogueActItem("silence"))

        if "_noise_" == u or "_laugh_" == u or "_ehm_hmm_" == u or "_inhale_" == u :
            cn.add(1.0, DialogueActItem("null"))

        if "_other_" == u or "__other__" == u:
            cn.add(1.0, DialogueActItem("other"))

    def parse_meta(self, utterance, cn):
        """
        Detects all dialogue acts which do not generalise its slot values using CLDB.

        :param utterance:
        :param cn:
        :return: None
        """
        u = utterance

        if (any_word_in(u, 'hello hi greetings') or
                all_words_in(u, 'good day')):
            cn.add(1.0, DialogueActItem("hello"))

        if (any_word_in(u, "bye byebye seeya goodbye") or
                all_words_in(u, 'good bye')):
            cn.add(1.0, DialogueActItem("bye"))

        if not any_word_in(u, 'connection station option'):
            if any_word_in(u, 'different another'):
                cn.add(1.0, DialogueActItem("reqalts"))

        if not any_word_in(u, 'connection station option last offer offered found beginning repeat begin'):
            if (any_word_in(u, 'repeat again') or
                phrase_in(u, "come again")):
                cn.add(1.0, DialogueActItem("repeat"))

        if phrase_in(u, "repeat the last sentence") or \
            phrase_in(u, "repeat what you've") or \
            phrase_in(u, "repeat what you have"):
            cn.add(1.0, DialogueActItem("repeat"))

        if len(u) == 1 and any_word_in(u, "excuse pardon sorry apology, apologise, apologies"):
            cn.add(1.0, DialogueActItem("apology"))

        if not any_word_in(u, "dont want thank you"):
            if any_word_in(u, "help hint"):
                cn.add(1.0, DialogueActItem("help"))

        if any_word_in(u, "hallo") or \
                all_words_in(u, 'not hear you'):

            cn.add(1.0, DialogueActItem('canthearyou'))

        if all_words_in(u, "did not understand") or \
            all_words_in(u, "didn\'t understand") or \
            all_words_in(u, "speek up") or \
            all_words_in(u, "can not hear you") or \
            (len(u) == 1 and any_word_in(u, "can\'t hear you")):
            cn.add(1.0, DialogueActItem('notunderstood'))

        if any_word_in(u, "yes yeah sure") and \
            not any_word_in(u, "end over option offer surrender") :
            cn.add(1.0, DialogueActItem("affirm"))

        if not any_phrase_in(u, ['not from', ]):
            if  any_word_in(u, "no not nope nono") or \
                 phrase_in(u, 'do not want') or \
                         len(u) == 2 and all_words_in(u, "not want") or \
                         len(u) == 3 and all_words_in(u, "yes do not") or \
                 all_words_in(u, "is wrong"):
                cn.add(1.0, DialogueActItem("negate"))

        if any_word_in(u, 'thanks thankyou thank cheers'):
            cn.add(1.0, DialogueActItem("thankyou"))

        if any_word_in(u, 'ok right well correct') and \
            not any_word_in(u, "yes"):
            cn.add(1.0, DialogueActItem("ack"))

        if any_word_in(u, "from begin begins") and any_word_in(u, "beginning scratch") or \
            any_word_in(u, "reset restart") or \
            phrase_in(u, 'new connection') and not phrase_in(u, 'connection from') or \
            phrase_in(u, 'new connection') and not phrase_in(u, 'from') or \
            phrase_in(u, 'new link') and not any_word_in(u, "from"):
            cn.add(1.0, DialogueActItem("restart"))

        if any_phrase_in(u, ['want to go', 'like to go', 'want to get', 'would like to get', ]):
            cn.add(1.0, DialogueActItem('inform', 'task', 'find_connection'))

        if any_phrase_in(u, ['what is the weather', 'will be the weather']):
            cn.add(1.0, DialogueActItem('inform', 'task', 'weather'))

        if all_words_in(u, 'where does it start') or \
            all_words_in(u, 'what is the initial') or \
            all_words_in(u, 'where departure ') or \
            all_words_in(u, 'where departuring') or \
            all_words_in(u, 'where departures') or \
            all_words_in(u, 'where starts') or \
            all_words_in(u, 'where goes from') or \
            all_words_in(u, 'where does go from') or \
            all_words_in(u, 'where will from'):
            cn.add(1.0, DialogueActItem('request', 'from_stop'))

        if all_words_in(u, 'where does it arrive') or \
            all_words_in(u, 'where does it stop') or \
            all_words_in(u, 'where stopping') or \
            all_words_in(u, 'where arriving') or \
            all_words_in(u, 'to what station') or \
            all_words_in(u, 'what is target') or \
            all_words_in(u, 'where is target') or \
            all_words_in(u, 'where destination') or \
            all_words_in(u, 'where terminates') or \
            all_words_in(u, "where terminal") or \
            all_words_in(u, "where terminate"):
            cn.add(1.0, DialogueActItem('request', 'to_stop'))

        if not any_phrase_in(u, ['will be', 'will arrive', 'will stop', 'will get to', ]):
            if all_words_in(u, "when does it go") or \
                all_words_in(u, "when does it leave") or \
                all_words_in(u, "what time") or \
                (any_word_in(u, 'when time') and  any_word_in(u, 'leave, departure, go')):
                cn.add(1.0, DialogueActItem('request', 'departure_time'))

        if not any_phrase_in(u, ['will be', 'will arrive', 'will stop', 'will get to', ]):
            if all_words_in(u, "how long till") or \
                all_words_in(u, "how long until") or \
                all_words_in(u, "how long before"):
                cn.add(1.0, DialogueActItem('request', 'departure_time_rel'))

        if (all_words_in(u, 'when will') and any_word_in(u, 'be arrive')) or \
            (all_words_in(u, 'when will i') and any_word_in(u, 'be arrive')) or \
            (all_words_in(u, 'what time will') and any_word_in(u, 'be arrive')) or \
            all_words_in(u, 'time of arrival') or \
            (any_word_in(u, 'when time') and  any_word_in(u, 'arrival arrive')):
            cn.add(1.0, DialogueActItem('request', 'arrival_time'))

        if all_words_in(u, 'how long till') and any_word_in(u, "get arrive") or \
            all_words_in(u, 'how long until') and (any_word_in(u, "target station") or \
                                                           any_word_in(u, "terminal station") or \
                                                           any_word_in(u, 'destination')):
            cn.add(1.0, DialogueActItem('request', 'arrival_time_rel'))

        if not any_word_in(u, 'till until'):
            if all_words_in(u, 'how long') and any_phrase_in(u, ['does it take', 'will it take', 'travel' ]):
                cn.add(1.0, DialogueActItem('request', 'duration'))

        if all_words_in(u, 'what time is it') or \
            all_words_in(u, 'what is the time') or \
            all_words_in(u, 'what\'s the time') or \
            all_words_in(u, 'what time do we have'):
            cn.add(1.0, DialogueActItem('request', 'current_time'))

        if all_words_in(u, 'how many') and \
            any_word_in(u, 'transfer transfers transfering changing change changes'
                           'interchange interchanging interchanges') and \
            not any_word_in(u, 'time'):
            cn.add(1.0, DialogueActItem('request', 'num_transfers'))

        if any_word_in(u, 'connection alternatives alternative option options found'):
            if any_word_in(u, 'arbitrary') and \
                not any_word_in(u, 'first second third fourth one two three four'):
                cn.add(1.0, DialogueActItem("inform", "alternative", "dontcare"))

            if any_word_in(u, 'first one') and \
                not any_word_in(u, 'second third fourth two three four'):
                cn.add(1.0, DialogueActItem("inform", "alternative", "1"))

            if any_word_in(u, 'second two')and \
                not any_word_in(u, 'third fourth next'):
                cn.add(1.0, DialogueActItem("inform", "alternative", "2"))

            if any_word_in(u, 'third three'):
                cn.add(1.0, DialogueActItem("inform", "alternative", "3"))

            if any_word_in(u, 'fourth four'):
                cn.add(1.0, DialogueActItem("inform", "alternative", "4"))

            if any_word_in(u, "last before latest lattermost bottom repeat again") and \
                not all_words_in(u, "previous"):
                cn.add(1.0, DialogueActItem("inform", "alternative", "last"))

            if any_word_in(u, "next different following subsequent later") or \
                phrase_in(u, "one more") or \
                phrase_in(u, "the next one"):
                cn.add(1.0, DialogueActItem("inform", "alternative", "next"))

            if any_word_in(u, "previous precedent"):
                if phrase_in(u, "not want to know previous"):
                    cn.add(1.0, DialogueActItem("deny", "alternative", "prev"))
                else:
                    cn.add(1.0, DialogueActItem("inform", "alternative", "prev"))

        if len(u) == 1 and any_word_in(u, 'next following'):
            cn.add(1.0, DialogueActItem("inform", "alternative", "next"))

        if len(u) == 2 and \
            (all_words_in(u, "and the following") or  all_words_in(u, "and afterwards")):
            cn.add(1.0, DialogueActItem("inform", "alternative", "next"))

        if len(u) == 1 and any_word_in(u, "previous precedent"):
            cn.add(1.0, DialogueActItem("inform", "alternative", "prev"))

        if any_phrase_in(u, ["by day", "of the day"]):
            cn.add(1.0, DialogueActItem('inform', 'ampm', 'pm'))


    def parse_1_best(self, obs, verbose=False):
        """Parse an utterance into a dialogue act."""
        utterance = obs['utt']

        if isinstance(utterance, UtteranceHyp):
            # Parse just the utterance and ignore the confidence score.
            utterance = utterance.utterance

        # print 'Parsing utterance "{utt}".'.format(utt=utterance)
        if verbose:
            print 'Parsing utterance "{utt}".'.format(utt=utterance)

        if self.preprocessing:
            # the text normalisation
            utterance = self.preprocessing.normalise_utterance(utterance)

            abutterance, category_labels = self.abstract_utterance(utterance)

            if verbose:
                print 'After preprocessing: "{utt}".'.format(utt=abutterance)
                print category_labels
        else:
            category_labels = dict()

        # handle false positive alarms of abstraction
        abutterance = abutterance.replace(('STOP=Metra',), ('metra',))
        abutterance = abutterance.replace(('STOP=Nádraží',), ('nádraží',))
        abutterance = abutterance.replace(('STOP=SME',), ('sme',))
        abutterance = abutterance.replace(('STOP=Bílá Hora', 'STOP=Železniční stanice',), ('STOP=Bílá Hora', 'železniční stanice',))

        abutterance = abutterance.replace(('TIME=now','bych', 'chtěl'), ('teď', 'bych', 'chtěl'))
        abutterance = abutterance.replace(('STOP=Čím','se'), ('čím', 'se',))
        abutterance = abutterance.replace(('STOP=Lužin','STOP=Na Chmelnici',), ('STOP=Lužin','na','STOP=Chmelnici',))
        abutterance = abutterance.replace(('STOP=Konečná','zastávka'), ('konečná', 'zastávka',))
        abutterance = abutterance.replace(('STOP=Konečná','STOP=Anděl'), ('konečná', 'STOP=Anděl',))
        abutterance = abutterance.replace(('STOP=Konečná stanice','STOP=Ládví'), ('konečná', 'stanice', 'STOP=Ládví',))
        abutterance = abutterance.replace(('STOP=Výstupní', 'stanice', 'je'), ('výstupní', 'stanice', 'je'))
        abutterance = abutterance.replace(('STOP=Nová','jiné'), ('nové', 'jiné',))
        abutterance = abutterance.replace(('STOP=Nová','spojení'), ('nové', 'spojení',))
        abutterance = abutterance.replace(('STOP=Nová','zadání'), ('nové', 'zadání',))
        abutterance = abutterance.replace(('STOP=Nová','TASK=find_connection'), ('nový', 'TASK=find_connection',))
        abutterance = abutterance.replace(('z','CITY=Liberk',), ('z', 'CITY=Liberec',))
        abutterance = abutterance.replace(('do','CITY=Liberk',), ('do', 'CITY=Liberec',))
        abutterance = abutterance.replace(('pauza','hrozně','STOP=Dlouhá',), ('pauza','hrozně','dlouhá',))
        abutterance = abutterance.replace(('v','STOP=Praga',), ('v', 'CITY=Praha',))
        abutterance = abutterance.replace(('na','STOP=Praga',), ('na', 'CITY=Praha',))
        abutterance = abutterance.replace(('po','STOP=Praga', 'ale'), ('po', 'CITY=Praha',))
        abutterance = abutterance.replace(('jsem','v','STOP=Metra',), ('jsem', 'v', 'VEHICLE=metro',))
        category_labels.add('CITY')
        category_labels.add('VEHICLE')

        # print 'After preprocessing: "{utt}".'.format(utt=abutterance)
        # print category_labels

        res_cn = DialogueActConfusionNetwork()

        self.parse_non_speech_events(utterance, res_cn)

        if len(res_cn) == 0:
            # remove non speech events, they are not relevant for SLU
            abutterance = abutterance.replace_all('_noise_', '').replace_all('_laugh_', '').replace_all('_ehm_hmm_', '').replace_all('_inhale_', '')

            if 'STOP' in category_labels:
                self.parse_stop(abutterance, res_cn)
            if 'CITY' in category_labels:
                self.parse_city(abutterance, res_cn)
            if 'TIME' in category_labels:
                self.parse_time(abutterance, res_cn)
            if 'DATE_REL' in category_labels:
                self.parse_date_rel(abutterance, res_cn)
            if 'AMPM' in category_labels:
                self.parse_ampm(abutterance, res_cn)
            if 'VEHICLE' in category_labels:
                self.parse_vehicle(abutterance, res_cn)
            if 'TASK' in category_labels:
                self.parse_task(abutterance, res_cn)

            self.parse_meta(utterance, res_cn)

        res_cn.merge()

        return res_cn
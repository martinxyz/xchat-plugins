__module_name__ = "bigroom"
__module_version__ = "1.3"
__module_description__ = "Highlight new questions and hide irrelevant join/part messages in noisy channels."
"""
Big Room Plugin for XChat

This script detects whether a channel is a big room and starts to hide
only the irrelevant join/part/nickchange messages for those
channels. It will also try hard to highlight questions that start a
new discussion thread. You can configure this below.

New command:
/act - displays the activity of the current channel

Not a new command, but good to know:
/lastlog text - search the current tab for text

2006-2009 Martin Renold (maxy on irc.freenode.net), public domain
"""

highlight_questions = True
highlight_questions_color = 7
highlight_questions_text = True # highlight the whole line?

# show a demo of all color numbers when loading
colortest = False

# user tresholds when a channel is considered noisy (the number of users)
numusers_lo = 40 # transition noisy ==> quiet
numusers_hi = 60 # transition quiet ==> noisy
# talk tresholds when a channel is considered noisy (the "multilog" value in /act)
noisy_lo = 2.5 # transition noisy ==> quiet
noisy_hi = 9.0 # transition quiet ==> noisy

# enable this if you don't want to wait until noisy channels get recognized
all_channels_are_noisy = False

# print all join/part/etc. messages that would be hidden with an explanation
debug = False

###############################################################################
# You can configure the hairy stuff below, but the defaults should work fine. #
###############################################################################

# Note: a monolog is counted as one line.
recent_lines_ignore1 = 50
recent_time = 10*60

slience_required_for_question_highlight = 60*60*24 # 30*60

# time constant (seconds); time to forget the activity of the channel
activity_T = 15*60

if all_channels_are_noisy:
    print 'DEBUG - all channels are considered noisy'
    noisy_lo = -2.0
    noisy_hi = -1.0

import xchat
import string, os
from time import time
from math import exp
import cPickle as pickle

BOLD = '\002'
COLOR = '\003'
BEEP = '\007'
RESET = '\017'
REVERSE = '\026'
UNDERLINE = '\037'

def nickeq(a, b):
    return xchat.nickcmp(a, b) == 0

def get_talk_partner(text):
    l = text.split()
    if not l: return None
    first_word = l[0]
    if first_word.endswith(':') or first_word.endswith(','):
        return first_word[:-1].strip()
    else:
        return None


class ActivityCounter:
    "floating average"
    def __init__(self, T=activity_T):
        self.T = T
        self.activity = 0.0
        self.last_t = time()
    def update(self):
        t = time()
        self.activity *= exp((self.last_t-t)/self.T)
        self.last_t = t
    def event(self, weight=1.0):
        self.update()
        self.activity += weight

class Nick:
    pass

class Context:
    "wraps and tracks an xchat context (a tab)"
    def __init__(self, identity):
        # ignoreJ = watch join/part
        # ignore0 = watch every line
        # ignore1 = ignore monologs
        # ignore2 = ignore dialogs

        self.identity = identity

        self.ignoreJ = ActivityCounter()
        self.ignore0 = ActivityCounter()
        self.ignore1 = ActivityCounter()
        self.ignore2 = ActivityCounter()
        self.ignore1.nick = None
        self.ignore2.nicks = []

        self.active_nicks = {}
        self.last_update = time()
        self.line = 0
        self.line_ignore1 = 0

        self.hidden_joins = []

        self.noisy = False

        if identity in activity_store:
            d = activity_store[identity]
            self.noisy = d['noisy']
            self.ignoreJ.activity = d.get('ignoreJ', 0.0)
            self.ignore0.activity = d['ignore0']
            self.ignore1.activity = d['ignore1']
            self.ignore2.activity = d['ignore2']
            if self.noisy:
                print '---\tbigroom.py: known noisy channel, hiding irrelevant joins/parts/nickchanges'

    def restored(self):
        # hack to ignore the big time gap
        self.ignoreJ.last_t = time()
        self.ignore0.last_t = time()
        self.ignore1.last_t = time()
        self.ignore2.last_t = time()


    def event(self, nick, talk=True):
        t = time()
        self.line += 1

        if not talk:
            self.ignoreJ.event()
        else:
            self.ignore0.event()

            if nick != self.ignore1.nick:
                self.line_ignore1 += 1
                self.ignore1.event()
                self.ignore1.nick = nick
            else:
                self.ignore1.update()

            if nick not in self.ignore2.nicks:
                self.ignore2.event()
                self.ignore2.nicks.append(nick)
                if len(self.ignore2.nicks) > 2:
                    self.ignore2.nicks.pop(0)
            else:
                self.ignore2.update()

            n = self.active_nicks.get(nick)
            if n is None:
                n = self.active_nicks[nick] = Nick()
                n.name = nick
                n.first_time = t
                n.question_highlighted = False
                n.highlight = 0
                n.join_seen = self.show_hidden_join(nick)
                n.lines = 0
            else:
                # reset stale question highlight blockers
                if t - n.last_time > slience_required_for_question_highlight:
                    n.question_highlighted = False

            n.last_line = self.line
            n.last_line_ignore1 = self.line_ignore1
            n.last_time = t
            n.lines += 1

        # count channel users
        res = xchat.get_list('users')
        if res:
            numusers = len(res)
        else:
            numusers = 0

        if not self.noisy and (self.ignore2.activity > noisy_hi or numusers > numusers_hi):
            print '---\tbigroom.py: channel is big or noisy, hiding irrelevant joins/parts/nickchanges'
            self.noisy = True

        if t - self.last_update > 60:
            if self.noisy and (self.ignore2.activity < noisy_lo and numusers < numusers_lo):
                print '---\tbigroom.py: channel is small and quiet, showing every join/part'
                self.noisy = False

            # throw out inactive nicks
            self.last_update = t
            new = {}
            for nick, n in self.active_nicks.iteritems():
                d_line_ignore1 = self.line_ignore1 - n.last_line_ignore1
                d_time = t - n.last_time
                if d_line_ignore1 < recent_lines_ignore1 or d_time < recent_time:
                    new[nick] = n
            self.active_nicks = new



        if self.identity not in activity_store:
            activity_store[self.identity] = {}

        d = activity_store[self.identity]
        d['noisy'] = self.noisy 
        d['ignoreJ'] = self.ignoreJ.activity 
        d['ignore0'] = self.ignore0.activity 
        d['ignore1'] = self.ignore1.activity 
        d['ignore2'] = self.ignore2.activity 

        activity_store_save() # save status if neccessary


    def register_hidden_join(self, nick, word):
        self.hidden_joins.append((nick, time(), word))
        if len(self.hidden_joins) > 20:
            self.hidden_joins.pop(0)


    def show_hidden_join(self, nick):
        for i, (nick2, t, word) in enumerate(self.hidden_joins):
            if nickeq(nick2, nick):
                del self.hidden_joins[i]
                dt = int(time() - t)
                if dt > 6*60:
                    # do as if he had been here forever
                    return False
                if dt/60.0 >= 2:
                    dt = '%d minutes ago' % int(dt/60.0)
                else:
                    dt = '%d seconds ago' % int(dt)
                print '-->\t%s has joined (%s)' % (nick2, dt)

                # showing a hidden join always counts as an event if
                # the nick did not say anything (to make sure we also
                # show the part)
                if nick2 not in self.active_nicks:
                    self.event(nick2)
                
                return True
        return False

    def clean_nick(self, nick2):
        for nick, n in self.active_nicks.iteritems():
            assert n.name == nick
            if nickeq(nick, nick2):
                return n
        return None

    def __str__(self):
        # update, just to get a bit faster feedback
        self.ignoreJ.update()
        self.ignore0.update()
        self.ignore1.update()
        self.ignore2.update()
        return 'active_nicks: %d, joinpart: %.1f, monolog: %.1f, dialog: %.1f, multilog: %.1f, noisy: %s' % (len(self.active_nicks), self.ignoreJ.activity, self.ignore0.activity, self.ignore1.activity, self.ignore2.activity, self.noisy)
        

contexts = {}

def get_context():
    channel = xchat.get_info('channel')
    network = xchat.get_info('network')
    if channel and network:
        i = (channel, network)
        if i not in contexts:
            contexts[i] = Context(i)
        return contexts[i]
    else:
        return None

def print_hook(word, word_eol, event): 
    c = get_context()
    if c is None: return


    nick = word[0]
    assert nick, word

    if event in ['Channel Message', 'Channel Msg Hilight']:
        c.event(nick)

        # talking to someone else?
        text = word[1]
        nick2 = get_talk_partner(text)
        if nick2:
            n2 = c.clean_nick(nick2)
        else:
            n2 = None
        del nick2
    elif event in ['Part', 'Part with Reason', 'Quit', 'Join']:
        # note: we later record this same event as a "normal" event
        # too if the nick was an active talker
        c.event(nick, talk=False)

    if event == 'Your Message':
        # let's see whom you're talking to
        text = word[1]
        nick2 = get_talk_partner(text)

    if not c.noisy: return

    #print 'nick=', nick, 'word=', word

    if event in ['Part', 'Part with Reason', 'Quit'] and nick not in c.active_nicks:
        if debug: print '(hiding part/quit of %s)' % nick
        return xchat.EAT_XCHAT

    if event == 'Join' and nick not in c.active_nicks:
        # let's see if a very similar nick to one of the active talkers joins
        # (someone with connection problems, probably)
        # (could do this a bit smarter with a alias table of known alternate nicks...)
        if len(nick) > 3:
            for nick2 in c.active_nicks:
                if len(nick2) > 3:
                    a = nick.lower()
                    b = nick2.lower()
                    if a.startswith(b) or b.startswith(a):
                        # show this join, and count this join as
                        # activity, to make sure we also show the part
                        c.event(nick)
                        return
        # maybe we want to show the join later
        c.register_hidden_join(nick, word)
        if debug: print '(hiding join of %s)' % nick
        return xchat.EAT_XCHAT

    if event == 'Change Nick':
        newnick = word[1]
        oldnick = nick
        if oldnick in c.active_nicks:
            if newnick in c.active_nicks:
                # fine. one event for both of you.
                c.event(oldnick)
                c.event(newnick)
            else:
                # "real" nickchange of an active user. one event for you
                n = c.active_nicks[oldnick]
                del c.active_nicks[oldnick]
                c.active_nicks[newnick] = n
                n.name = newnick
                c.event(newnick)
        elif newnick in c.active_nicks:
            # inactive user changes his nick to a name with activity
            # (happens when someone rejoins, then kills his ghost, and changes to the correct nick)
            # this is usually relevant for the discussion

            # one event for both of you.
            # this will automatically show hidden joins
            c.event(newnick)
            c.event(oldnick)
        else:
            # there is no need to show this nickchange, even if he starts talking after this
            if debug: print '(hiding nickchange %s ==> %s)' % (oldnick, newnick)
            return xchat.EAT_XCHAT

    if event == 'Channel Message':
        text = word[1]
        n = c.active_nicks[nick]
        t = time()

        # talking to someone else?
        nick2 = get_talk_partner(text)

        if nick2:
            c.show_hidden_join(nick2)

            # could also be 'hi, I have a question...', where 'hi' is
            # interpreted as talk partner

            # if we have just seen you join (displayed a delayed join
            # message, that is), then you are worth highlighting

            # do we know the person you're talking to?
            n2 = c.clean_nick(nick2)

            if n2:
                # you're talking to someone we know, you're not going to get a question highlight
                n.question_highlighted = True
                return

        if n.question_highlighted:
            # you already got one...
            return

        if t - n.first_time < 1*60 or n.lines < 3:
            #                         ^^^^^^^^^^^ allow to say "hi" first
            # you just joined the talk
            highlight = False
            if len(text) > 15 and '?' in text:
                highlight = True
            if len(text) > 25 and n.join_seen:
                highlight = True
            if c.line < 25 and not n.join_seen:
                # we're not yet listening long enough to make a good decision
                # let's assume you are in the middle of a conversation
                n.question_highlighted = True
                return
            if highlight:
                n.question_highlighted = True
                if not highlight_questions: return
                if highlight_questions_text:
                    print COLOR+'2<'+RESET+nick+COLOR+'2>'+RESET+'\t'+COLOR+str(highlight_questions_color)+text+RESET
                else:
                    print COLOR+'2<'+COLOR+str(highlight_questions_color)+nick+COLOR+'2>'+RESET+'\t'+text+RESET

                return xchat.EAT_XCHAT

#xchat.hook_server("PRIVMSG", privmsg)

for s in ['Join', 'Part', 'Part with Reason', 'Quit', 'Change Nick', 'Channel Message', 'Channel Msg Hilight', 'Your Message']:
    xchat.hook_print(s, print_hook, userdata=s)

def show_activity(word, word_eol, userdata): 
    c = get_context()
    if not c:
        print 'no channel tab'
        return
    print 'activity %s - %s' % (xchat.get_info('channel') or '<no channel>', c)
    return xchat.EAT_ALL 

xchat.hook_command("ACT", show_activity, help="/ACT - show activity average of current tab") 

# persistency

activity_store_filename = os.path.join(xchat.get_info("xchatdir"), 'bigroom.pik')
try: 
    print "Reading ", activity_store_filename
    activity_store = pickle.load(open(activity_store_filename, 'rb'))
except:
    activity_store = {}
    print "Not found. Starting from zero."
    print "---"
    print "Looks like this is the first you use bigroom.py."
    print "Be patient, it can take a few hours until a channel is recognized as noisy."
    print "You can use the /act command in each channel to see some statistics."
    print COLOR+str(highlight_questions_color) + "This is the color that will be used for highlighted questions." + RESET
    print "You can change it by editing " + __file__
    print "---"


save_time = time()
def activity_store_save():
    global save_time
    if time() - save_time > 2*60:
        if debug: print 'writing', activity_store_filename
        pickle.dump(activity_store, open(activity_store_filename, 'wb'))
        save_time = time()
        

#for name in dir(xchat):
#    print name, '=', xchat.__dict__[name]

if colortest:
    for i in range(20):
        print 'Color', i, ': ' + COLOR + str(i) + 'Blah' + BOLD + ' Blah' + RESET + 'end.'

print "bigroom.py loaded"

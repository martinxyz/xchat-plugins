__module_name__ = "bigroom"
__module_version__ = "1.0"
__module_description__ = "hide irrelevant join/part/nickchanges in noisy channels, highlight newcomer questions"
"""
Big Room Plugin for XChat

If you hang around in one of the big support channels on freenode.net,
then this script is for you. It automatically detects whether a
channel is a big room and will start to hide only the
join/part/nickchange messages which are unrelated.

It will also highlight questions of newcomers, and threads you are
involved into, and threads of your choice. The highlighting features
can be disabled below.

Commands:
/act - displays the activity of the current channel
/foc <somenick> - focus on that nick (highlight his threads for a while)

FIXME: auto-highlight treads is experimental; it might highlight too
       much, too long and leak the highlighting into unrelated
       threads. But it is still very useful.

2006 Martin Renold (maxy on irc.freenode.net), public domain
"""

highlight_questions = True
highlight_questions_color = 7
highlight_questions_text = True # highlight the whole line?

highlight_nicks = True # highlight nicks you're talking to, for a while
highlight_nicks_points = 20 # lines after which highlighting turns off
highlight_nicks_propagate = True # also highlight nicks he is talking to
highlight_nicks_color = 9 # 11
highlight_nicks_text = False # highlight the whole line?

# show a demo of all color numbers when loading
colortest = False


###############################################################################
# You can configure the hairy stuff below, but the defaults should work fine. #
###############################################################################

# display when messages are hidden
debug = False

# If a nick has talked either less than (recent_lines) lines ago, or
# less than (recent_time) seconds ago, it is considered active.
# Note: a monolog is counted as one line.
recent_lines_ignore1 = 50
recent_time = 10*60

# time constant (seconds); time to forget the activity of the channel
activity_T = 15*60
# tresholds when a channel is considered noisy (the "multilog" value in /act)
noisy_lo = 9.0
noisy_hi = 17.0

if debug:
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
        # ignore0 = watch every line
        # ignore1 = ignore monologs
        # ignore2 = ignore dialogs

        self.identity = identity

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
        self.highlight_nicks_when_quiet = False

        if identity in activity_store:
            d = activity_store[identity]
            self.noisy = d['noisy']
            self.ignore0.activity = d['ignore0']
            self.ignore1.activity = d['ignore1']
            self.ignore2.activity = d['ignore2']
            if self.noisy:
                print '---\tknown noisy channel, hiding irrelevant joins/parts/nickchanges'

    def restored(self):
        # hack to ignore the big time gap
        self.ignore0.last_t = time()
        self.ignore1.last_t = time()
        self.ignore2.last_t = time()


    def event(self, nick):
        t = time()
        self.line += 1

        self.ignore0.event()

        if nick != self.ignore1.nick:
            self.line_ignore1 += 1
            self.ignore1.event()
            self.ignore1.nick = nick
        if nick not in self.ignore2.nicks:
            self.ignore2.event()
            self.ignore2.nicks.append(nick)
            if len(self.ignore2.nicks) > 2:
                self.ignore2.nicks.pop(0)

        n = self.active_nicks.get(nick)
        if n is None:
            n = self.active_nicks[nick] = Nick()
            n.first_time = t
            n.question_highlighted = False
            n.highlight = 0
            n.join_seen = self.show_hidden_join(nick)
        n.last_line = self.line
        n.last_line_ignore1 = self.line_ignore1
        n.last_time = t

        if not self.noisy and self.ignore2.activity > noisy_hi:
            print '---\tnoisy channel, hiding irrelevant joins/parts/nickchanges'
            self.noisy = True

        if t - self.last_update > 60:
            if self.noisy and self.ignore2.activity < noisy_lo:
                print '---\tchannel is quiet, showing every join/part'
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
            if nick2 == nick:
                print '-->\t%s has joined (%d seconds ago)' % (nick, int(time() - t))
                del self.hidden_joins[i]
                return True
        return False

    def watch_nick(self, nick2, points=highlight_nicks_points):
        for nick, n in self.active_nicks.iteritems():
            if nickeq(nick, nick2):
                n.highlight = max(points, n.highlight)
                if debug: print 'watching', nick, 'with', n.highlight, 'points'
                return nick, n.highlight
        if debug: print 'not watching', nick2, ' - not found'
        return None, None

    def clean_nick(self, nick2):
        for nick, n in self.active_nicks.iteritems():
            if nickeq(nick, nick2):
                return nick, n
        return None, None

    def __str__(self):
        return 'active_nicks: %d, monolog: %.1f, dialog: %.1f, multilog: %.1f, noisy: %s' % (len(self.active_nicks), self.ignore0.activity, self.ignore1.activity, self.ignore2.activity, self.noisy)
        

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
        nick2, n2 = None, None
        text = word[1]
        first_word = text.split()[0]
        if first_word.endswith(':') or first_word.endswith(','):
            nick2 = first_word[:-1].strip()
            nick2, n2 = c.clean_nick(nick2)

        if c.highlight_nicks_when_quiet or (highlight_nicks and c.noisy):
            n = c.active_nicks[nick]
            t = time()

            if n.highlight or (n2 and n2.highlight):
                if n.highlight:
                    n.highlight -= 1
                    if n2 and n2.highlight > n.highlight:
                        n2.highlight -= 1
                else:
                    n2.highlight -= 1

                if n2 and highlight_nicks_propagate:
                    c.watch_nick(nick2, n.highlight)
                    c.watch_nick(nick, n2.highlight)
                    
                # make sure he doesn't get a question highlight later
                n.question_highlighted = True

                if event == 'Channel Msg Hilight':
                    return # no need for more hilight

                if highlight_nicks_text:
                    #print COLOR+'2<'+COLOR+str(highlight_nicks_color)+nick+COLOR+'2>'+RESET+'\t'+COLOR+str(highlight_nicks_color)+text+RESET
                    print COLOR+'2<'+RESET+nick+COLOR+'2>'+RESET+'\t'+COLOR+str(highlight_nicks_color)+text+RESET
                else:
                    print COLOR+'2<'+COLOR+str(highlight_nicks_color)+nick+COLOR+'2>'+RESET+'\t'+text+RESET
                return xchat.EAT_XCHAT

    if event == 'Your Message':
        # let's see whom you're talking to
        text = word[1]
        first_word = text.split()[0]
        if first_word.endswith(':') or first_word.endswith(','):
            nick2 = first_word[:-1].strip()
            c.watch_nick(nick2)

    if event == 'Channel Msg Hilight':
        c.watch_nick(nick)

    if not c.noisy: return # display everything

    #print 'nick=', nick, 'word=', word

    if event in ['Part', 'Part with Reason', 'Quit'] and nick not in c.active_nicks:
        if debug: print '(hiding part/quit of %s)' % nick
        #print '<%C10-%C11-%O\t$1 %C14(%O$2%C14)%C bleh left $3 %C14(%O$4%C14)%O '
        #c = chr(3)
        #print 'before_tab\tafter_tab '+c+'10c10'+c+'11c11'
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
                        # show this join
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
                pass # fine
            else:
                c.active_nicks[newnick] = c.active_nicks[oldnick]
                del c.active_nicks[oldnick]
        elif newnick in c.active_nicks:
            # inactive user changes his nick to a name with activity
            # (happens when someone rejoins, then kills his ghost, and changes to the correct nick)
            # this is usually relevant for the discussion
            c.show_hidden_join(oldnick)
        else:
            # there is no need to show this nickchange, even if he starts talking after this
            if debug: print '(hiding nickchange %s ==> %s)' % (oldnick, newnick)
            return xchat.EAT_XCHAT

    if event == 'Channel Message':
        text = word[1]
        n = c.active_nicks[nick]
        t = time()

        if n.question_highlighted:
            # you already got one...
            return

        first_word = text.split()[0]
        if first_word.endswith(':') or first_word.endswith(','):
            # you're talking to someone, you're not going to get a question highlight
            n.question_highlighted = True
            return

        if t - n.first_time < 60:
            # you just joined the talk, or started talking <60s ago
            highlight = False
            if len(text) > 15 and '?' in text:
                highlight = True
            if len(text) > 25 and n.join_seen:
                highlight = True
            if c.line < 25 and not n.join_seen:
                return # we're not yet listening long enough to make a good decision
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

def focus(word, word_eol, userdata): 
    c = get_context()
    if not c:
        print 'no channel tab'
        return

    if not c.highlight_nicks_when_quiet and not c.noisy:
        print 'Enabling nick highlighting for this channel and session.'
    c.highlight_nicks_when_quiet = True

    if len(word) > 2:
        nick, points = c.watch_nick(word[1], int(word[2]))
    else:
        nick, points = c.watch_nick(word[1])

    if nick:
        print 'Focussing on', nick, 'with', points, 'points'
    else:
        print 'No such nick among the active talkers!'

    return xchat.EAT_ALL 
 
xchat.hook_command("ACT", show_activity, help="/ACT - show activity average of current tab") 
xchat.hook_command("FOC", focus, help="/FOC nick [lines] - focus on (highlight) the discussion that nick is having; optionally give the maximum number of lines to highlight")


# persistency

activity_store_filename = os.path.join(xchat.get_info("xchatdir"), 'bigroom.pik')
try: 
    print "Reading ", activity_store_filename
    activity_store = pickle.load(open(activity_store_filename, 'rb'))
except:
    activity_store = {}
    print "Failed. Starting from zero."
    print "Be patient, it will take a few minutes until a big room is recognized."

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

if debug:
    print 'debug mode - all channels are considered noisy'
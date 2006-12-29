__module_name__ = "antiaway"
__module_version__ = "1.0"
__module_description__ = "emoted away messages don't highlight the channel"
 
# lowercase list of word to be blocked, when appearing in an emote
blockwords = ["away", "back", "gone", "afk"]

import xchat
import string

def privmsg(word, word_eol, userdata): 
    #xchat.prnt("This is word: " + `word`) 
    #xchat.prnt("This is word_eol: " + `word_eol`) 
    if len(word_eol) > 4 and word[3] == ':\x01ACTION':
        text = word_eol[4].lower()
        for blockword in blockwords:
            if text.find(blockword) != -1:
                # print it almost "as usual" but block the event
                xchat.prnt("* " + word[0].split('!')[0][1:] + " " + word_eol[4][:-1])
                return xchat.EAT_XCHAT
    return xchat.EAT_NONE
 
xchat.hook_server("PRIVMSG", privmsg)

print "AntiAway ready."

#for name in dir(xchat):
#    print name, '=', xchat.__dict__[name]

#print 'XCHAT_PRI_NORM = ', xchat.PRI_NORM

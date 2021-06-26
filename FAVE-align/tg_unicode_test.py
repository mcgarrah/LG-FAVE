#!/usr/bin/python

#import io
import praat

"""
https://github.com/kylebgorman/textgrid/blob/master/textgrid/textgrid.py
https://stackoverflow.com/questions/6048085/writing-unicode-text-to-a-text-file


Conversion by using the io.open() will require changing all the f.write() calls.
First fail...

Going to attempt a light touch with an addition of a String.encode('utf8') and String.decode('utf8) to make this work.
Causes an issue with an encoded 1252 ANSI when combined with UTF-8...
Second fail...

An alternative if we revisit the io.open() is to use the u"unicode string" rather than the "ascii string"
https://stackoverflow.com/questions/21386165/python-how-to-solve-unicodeencodeerror


"""

def print_tg(tg):
    print tg.name()
    for textgrid in tg:
        print textgrid.name()
        for (i, interval) in enumerate(textgrid):
            print "\t%s" % interval.mark()

tg = praat.TextGrid()
print_tg(tg)
tg.read('./examples/sv_SE/gen_test/unicode_test_in.TextGrid')
print_tg(tg)
tg.write('./examples/sv_SE/gen_test/unicode_test_out.TextGrid')
print_tg(tg)

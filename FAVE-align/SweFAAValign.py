#!/usr/bin/env python

"""
Usage:  (python) FAAValign.py [options] soundfile.wav [transcription.txt] [output.TextGrid]

Aligns a sound file with the corresponding transcription text. The
transcription text is split into annotation breath groups, which are fed
individually as "chunks" to the forced aligner. All output is concatenated
into a single Praat TextGrid file.

INPUT:
- sound file
- tab-delimited text file with the following columns:
    first column:   speaker ID
    second column:  speaker name
    third column:   beginning of breath group (in seconds)
    fourth column:  end of breath group (in seconds)
    fifth column:   transcribed text
(If no name is specified for the transcription file, it will be assumed to
have the same name as the sound file, plus ".txt" extension.)

OUTPUT:
- Praat TextGrid file with orthographic and phonemic transcription tiers for
each speaker (If no name is specified, it will be given same name as the sound
file, plus ".TextGrid" extension.)


Options:

--version ("version"):

    Prints the program's version string and exits.

-h, --help ("help):

    Show this help message and exits.

-c [filename], --check=[filename] ("check transcription"):

    Checks whether phonetic transcriptions for all words in the transcription file can be found in the
    CMU Pronouncing Dictionary (file "dict").  Returns a list of unknown words.

-i [filename], --import=[filename] ("import dictionary entries"):

    Adds a list of unknown words and their corresponding phonetic transcriptions to the CMU Pronouncing
    Dictionary prior to alignment.  User will be prompted interactively for the transcriptions of any
    remaining unknown words.  File must be tab-separated plain text file.

-v, --verbose ("verbose"):

    Detailed output on status of dictionary check and alignment progress.

-d [filename], --dict=[filename] ("dictionary"):

    Specifies the name of the file containing the pronunciation dictionary.  Default file is "/model/dict".

-n, --noprompt ("no prompt"):

-t HTKTOOLSPATH, --htktoolspath=HTKTOOLSPATH
    Specifies the path to the HTKTools directory where the HTK executable files are located.  If not specified, the user's path will be searched for the location of the executable.

    User is not prompted for the transcription of words not in the dictionary, or truncated words.  Unknown words are ignored by the aligner.
"""

################################################################################
## PROJECT "AUTOMATIC ALIGNMENT AND ANALYSIS OF LINGUISTIC CHANGE"            ##
## FAAValign.py                                                               ##
## written by Ingrid Rosenfelder                                              ##
################################################################################

import os
import sys
import shutil
import re
import wave
import optparse
import time
import praat
import subprocess
import traceback
import codecs
import subprocess
import string

truncated = re.compile(r'\w+\-$')                       ## truncated words
intended = re.compile(r'^\+\w+')                        ## intended word (inserted by transcribers after truncated word)
## NOTE:  earlier versions allowed uncertain/unclear transcription to use only one parenthesis,
##        but this is now back to the strict definition
##        (i.e. uncertain/unclear transcription spans MUST be enclosed in DOUBLE parentheses)
unclear = re.compile(r'\(\(\s*\)\)')                    ## unclear transcription (empty double parentheses)
start_uncertain = re.compile(r'(\(\()')                 ## beginning of uncertain transcription
end_uncertain = re.compile(r'(\)\))')                   ## end of uncertain transcription
uncertain = re.compile(r"\(\(([\*\+]?['\w]+\-?)\)\)")   ## uncertain transcription (single word)
ing = re.compile(r"IN'$")                               ## words ending in "in'"
hyphenated = re.compile(r'(\w+)-(\w+)')                 ## hyphenated words

CONSONANTS = ['B', 'BB', 'CH', 'D', 'DD', 'DH','F', 'G', 'GG', 'HH', 'J', 'JH', 'K', 'KK', 'L', 'M', 'N', 'NG', 'P', 'PP', 'R', 'RD', 'RL', 'RN', 'RR', 'RS', 'RT', 'RX', 'RXX', 'S', 'SJ', 'T', 'TT', 'TH', 'TJ', 'V', 'W', 'Z', 'ZH']
VOWELS = ['AA', 'AE', 'AEE', 'AEH', 'AH', 'AJ', 'AU', 'EE', 'EH', 'EJ', 'ER', 'EU', 'IH', 'II', 'OA', 'OAH', 'OE', 'OEE', 'OEH', 'OH', 'OJ', 'OO', 'UH', 'UU', 'YH', 'YY']
STYLE = ["style", "Style", "STYLE"]
STYLE_ENTRIES = ["R", "N", "L", "G", "S", "K", "T", "C", "WL", "MP", "SD", "RP"]

#TEMPDIR = "temp_FA"
TEMPDIR = ""
DICT_ADDITIONS = "added_dict_entries.txt"               ## file for collecting uploaded additions to the dictionary
PRAATPATH = "/usr/local/bin/praat"                      ## this is just in case the wave module does not work (use Praat instead to determe the length of the sound file)
##PRAATPATH = "/Applications/Praat.app/Contents/MacOS/praat"  ## old setting on ingridpc.ling.upenn.edu

################################################################################

def add_dictionary_entries(infile, FADIR):
    """reads additional dictionary entries from file and adds them to the CMU dictionary"""
    ## INPUT:  string infile = name of tab-delimited file with word and Arpabet transcription entries
    ## OUTPUT:  none, but modifies CMU dictionary (cmudict)

    ## read import file
    i = open(infile, 'rU')
    lines = i.readlines()
    i.close()

    global cmudict
    add_dict = {}

    ## process entries
    for line in lines:
        try:
            word = line.strip().split('\t')[0].upper()
            trans = [check_transcription(t.strip()) for t in line.strip().split('\t')[1].replace('"', '').split(',')]
            ## (transcriptions will be converted to upper case in check_transcription)
            ## (possible to have more than one (comma-separated) transcription per word in input file)
        except IndexError:
            error = "ERROR!  Incorrect format of dictionary input file %s:  Problem with line \"%s\"." % (infile, line)
            errorhandler(error)
        ## add new entry to CMU dictionary
        if word not in cmudict and trans:
            cmudict[word] = trans
            add_dict[word] = trans
        else:   ## word might be in dict but transcriber might want to add alternative pronunciation
            for t in trans:
                if t and (t not in cmudict[word]):  ## check that new transcription is not already in dictionary  
                    cmudict[word].append(t)
                    add_dict[word] = [t]

    if options.verbose:
        print "Added all entries in file %s to CMU dictionary." % os.path.basename(infile)

    ## add new entries to the file for additional transcription entries
    ## (merge with the existing DICT_ADDITIONS file to avoid duplicates)
    if os.path.exists(os.path.join(FADIR, DICT_ADDITIONS)):  ## check whether dictionary additions file exists already
        added_already = read_dict(os.path.join(FADIR, DICT_ADDITIONS))
        new_dict = merge_dicts(added_already, add_dict)
    else:
        new_dict = add_dict
    write_dict(os.path.join(FADIR, DICT_ADDITIONS), dictionary=new_dict, mode='w')
    if options.verbose:
        print "Added new entries from file %s to file %s." % (os.path.basename(infile), DICT_ADDITIONS)


## This was the main body of Jiahong Yuan's original align.py
def align(wavfile, trs_input, outfile, FADIR='', SOXPATH='', HTKTOOLSPATH=''):
    """calls the forced aligner"""
    ## wavfile = sound file to be aligned
    ## trsfile = corresponding transcription file
    ## outfile = output TextGrid
    
    ## change to Forced Alignment Toolkit directory for all the temp and preparation files
    if FADIR:
        os.chdir(FADIR)

    ## derive unique identifier for tmp directory and all its file (from name of the sound "chunk")
    identifier = re.sub(r'\W|_|chunk', '', os.path.splitext(os.path.split(wavfile)[1])[0])
    ## old names:  --> will have identifier added
    ## - "tmp"
    ## - "aligned.mlf"
    ## - "aligned.results"
    ## - "codetr.scp"
    ## - "test.scp"
    ## - "tmp.mlf"
    ## - "tmp.plp"
    ## - "tmp.wav"
    
    # create working directory  
    os.mkdir("./tmp" + identifier)
    # prepare wavefile
    SR = prep_wav(wavfile, './tmp' + identifier + '/tmp' + identifier + '.wav', SOXPATH)

    # prepare mlfile
    prep_mlf(trs_input, './tmp' + identifier + '/tmp' + identifier + '.mlf', identifier)
 
    # prepare scp files
    fw = open('./tmp' + identifier + '/codetr' + identifier + '.scp', 'w')
    fw.write('./tmp' + identifier + '/tmp' + identifier + '.wav ./tmp' + identifier + '/tmp'+ identifier + '.plp\n')
    fw.close()
    fw = open('./tmp' + identifier + '/test' + identifier + '.scp', 'w')
    fw.write('./tmp' + identifier +'/tmp' + identifier + '.plp\n')
    fw.close()

    try:
        # call plp.sh and align.sh
        if HTKTOOLSPATH:  ## if absolute path to HTK Toolkit is given
            os.system(os.path.join(HTKTOOLSPATH, 'HCopy') + ' -T 1 -C ./model/' + str(SR) + '/config -S ./tmp' + identifier + '/codetr' + identifier + '.scp >> ./tmp' + identifier + '/blubbeldiblubb.txt')
            os.system(os.path.join(HTKTOOLSPATH, 'HVite') + ' -T 1 -a -m -I ./tmp' + identifier + '/tmp' + identifier +'.mlf -H ./model/' + str(SR) + '/macros -H ./model/' + str(SR) + '/hmmdefs  -S ./tmp' + identifier + '/test' + identifier+ '.scp -i ./tmp' + identifier + '/aligned' + identifier + '.mlf -p 0.0 -s 5.0 ' + options.dict + ' ./model/monophones > ./tmp' + identifier + '/aligned' + identifier + '.results')
        else:  ## find path via shell
            #os.system('HCopy -T 1 -C ./model/' + str(SR) + '/config -S ./tmp/codetr.scp >> blubbeldiblubb.txt')
            #os.system('HVite -T 1 -a -m -I ./tmp/tmp.mlf -H ./model/' + str(SR) + '/macros -H ./model/' + str(SR) + '/hmmdefs  -S ./tmp/test.scp -i ./tmp/aligned.mlf -p 0.0 -s 5.0 ' + options.dict + ' ./model/monophones > ./tmp/aligned.results')
            os.system('HCopy -T 1 -C ./model/' + str(SR) + '/config -S ./tmp' + identifier + '/codetr' + identifier + '.scp >> ./tmp' + identifier + '/blubbeldiblubb.txt')
            os.system('HVite -T 1 -a -m -I ./tmp' + identifier + '/tmp' + identifier +'.mlf -H ./model/' + str(SR) + '/macros -H ./model/' + str(SR) + '/hmmdefs  -S ./tmp' + identifier + '/test' + identifier+ '.scp -i ./tmp' + identifier + '/aligned' + identifier + '.mlf -p 0.0 -s 5.0 ' + options.dict + ' ./model/monophones > ./tmp' + identifier + '/aligned' + identifier + '.results')

        ## write result of alignment to TextGrid file
        aligned_to_TextGrid('./tmp' + identifier + '/aligned' + identifier + '.mlf', outfile, SR)
        if options.verbose:
            print "\tForced alignment called successfully for file %s." % os.path.basename(wavfile)
    except Exception, e:
        FA_error = "Error in aligning file %s:  %s." % (os.path.basename(wavfile), e)
        ## clean up temporary alignment files
        shutil.rmtree("./tmp" + identifier)
        raise Exception, FA_error
        ##errorhandler(FA_error)

    ## remove tmp directory and all files        
    shutil.rmtree("./tmp" + identifier)
    

## This function is from Jiahong Yuan's align.py
## (originally called "TextGrid(infile, outfile, SR)")
def aligned_to_TextGrid(infile, outfile, SR):
    """writes the results of the forced alignment (file "aligned.mlf") to file as a Praat TextGrid file"""
    
    f = open(infile, 'rU')
    lines = f.readlines()
    f.close()
    fw = open(outfile, 'w')
    j = 2
    phons = []
    wrds = []
##    try:
    while (lines[j] <> '.\n'):
        ph = lines[j].split()[2]  ## phone
        if (SR == 11025):  ## adjust rounding error for 11,025 Hz sampling rate
            ## convert time stamps from 100ns units to seconds
            ## fix overlapping intervals:  divide time stamp by ten first and round!
            st = round((round(float(lines[j].split()[0])/10.0, 0)/1000000.0)*(11000.0/11025.0) + 0.0125, 3)  ## start time 
            en = round((round(float(lines[j].split()[1])/10.0, 0)/1000000.0)*(11000.0/11025.0) + 0.0125, 3)  ## end time
        else:
            st = round(round(float(lines[j].split()[0])/10.0, 0)/1000000.0 + 0.0125, 3)
            en = round(round(float(lines[j].split()[1])/10.0, 0)/1000000.0 + 0.0125, 3)
        if (st <> en):  ## 'sp' states between words can have zero duration
            phons.append([ph, st, en])  ## list of phones with start and end times in seconds

        if (len(lines[j].split()) == 5):  ## entry on word tier
            wrd = lines[j].split()[4].replace('\n', '') 
            if (SR == 11025):
                st = round((round(float(lines[j].split()[0])/10.0, 0)/1000000.0)*(11000.0/11025.0) + 0.0125, 3)
                en = round((round(float(lines[j].split()[1])/10.0, 0)/1000000.0)*(11000.0/11025.0) + 0.0125, 3)
            else:
                st = round(round(float(lines[j].split()[0])/10.0, 0)/1000000.0 + 0.0125, 3)
                en = round(round(float(lines[j].split()[1])/10.0, 0)/1000000.0 + 0.0125, 3)
            if (st <> en):
                wrds.append([wrd, st, en])

        j += 1
##    except Exception, e:
##        FA_error = "Error in converting times from file %s in line %d for TextGrid %s:  %s." % (os.path.basename(infile), j + 1, os.path.basename(outfile), e)
##        errorhandler(FA_error)
        
##    try:
    #write the phone interval tier
    fw.write('File type = "ooTextFile short"\n')
    fw.write('"TextGrid"\n')
    fw.write('\n')
    fw.write(str(phons[0][1]) + '\n')
    fw.write(str(phons[-1][2]) + '\n')
    fw.write('<exists>\n')
    fw.write('2\n')
    fw.write('"IntervalTier"\n')
    fw.write('"phone"\n')
    fw.write(str(phons[0][1]) + '\n')
    fw.write(str(phons[-1][-1]) + '\n')
    fw.write(str(len(phons)) + '\n')
    for k in range(len(phons)):
        fw.write(str(phons[k][1]) + '\n')
        fw.write(str(phons[k][2]) + '\n')
        fw.write('"' + phons[k][0] + '"' + '\n')
##    except Exception, e:
##        FA_error = "Error in writing phone interval tier for TextGrid %s:  %s." % (os.path.basename(outfile), e)
##        errorhandler(FA_error)
##    try:
    #write the word interval tier
    fw.write('"IntervalTier"\n')
    fw.write('"word"\n')
    fw.write(str(phons[0][1]) + '\n')
    fw.write(str(phons[-1][-1]) + '\n')
    fw.write(str(len(wrds)) + '\n')
    for k in range(len(wrds) - 1):
        fw.write(str(wrds[k][1]) + '\n')
        fw.write(str(wrds[k+1][1]) + '\n')
        fw.write('"' + wrds[k][0] + '"' + '\n')
    fw.write(str(wrds[-1][1]) + '\n')
    fw.write(str(phons[-1][2]) + '\n')
    fw.write('"' + wrds[-1][0] + '"' + '\n')
##    except Exception, e:
##        FA_error = "Error in writing phone interval tier for TextGrid %s:  %s." % (os.path.basename(outfile), e)
##        errorhandler(FA_error)

    fw.close()


def check_arguments(args):
    """returns sound file, transcription file and output TextGrid file from positional arguments from command line"""

    ## no or too many positional arguments
    if len(args) == 0 or len(args) > 3:
        error = "ERROR!  Incorrect number of arguments: %s" % args
        errorhandler(error)
    ## sound file must be present and first positional argument
    ## EXCEPT when checking for unknown words!
    elif is_sound(args[0]) or options.check:
        ## case A:  sound file is first argument
        if is_sound(args[0]):
            wavfile = check_file(args[0])
            if len(args) == 1:  ## only sound file given
                trsfile = check_file(replace_extension(wavfile, ".txt"))
                tgfile = replace_extension(wavfile, ".TextGrid")
            elif len(args) == 2:
                if is_text(args[1]):  ## sound file and transcription file given
                    trsfile = check_file(args[1])
                    tgfile = replace_extension(wavfile, ".TextGrid")
                elif is_TextGrid(args[1]):  ## sound file and output TextGrid given
                    tgfile = args[1]
                    trsfile = check_file(replace_extension(wavfile, ".txt"))  ## transcription file name must match sound file
            elif len(args) == 3:  ## all three arguments given
                trsfile = check_file(args[1])
                tgfile = args[2]
            else:  ## this should not happen
                error = "Something weird is going on here..."
                errorhandler(error)
        ## case B:  unknown words check, no sound file
        elif options.check:
            wavfile = ''
            ## if run from the command line, the first file must now be the transcription file
            ## if run as a module, the first argument will be an empty string for the sound file, and the transcription file is still the second argument
            if (__name__ == "__main__" and is_text(args[0])) or (__name__ != "__main__" and is_text(args[1])):
                if (__name__ == "__main__" and is_text(args[0])):
                    trsfile = check_file(args[0])
                elif (__name__ != "__main__" and is_text(args[1])):
                    trsfile = check_file(args[1])
                tgfile = replace_extension(trsfile, ".TextGrid")  ## need to have a name for the TextGrid for the name of the outputlog (renamed from original name of the TextGrid later)
            else:
                error = "ERROR!  Transcription file needed for unknown words check."
                if __name__ == "__main__":
                    print error
                    sys.exit(parser.print_usage())
                else:
                    raise Exception, error               
        else:  ## this should not happen
            error = "Something weird is going on here!!!"
            errorhandler(error)
    else:  ## no sound file, and not checking unknown words
        error = "ERROR!  First argument to program must be sound file."
        if __name__ == "__main__":
            print error
            sys.exit(parser.print_usage())
        else:
            raise Exception, error

    return (wavfile, trsfile, tgfile)


def check_dictionary_entries(lines, wavfile):
    """checks that all words in lines have an entry in the CMU dictionary;
    if not, prompts user for Arpabet transcription and adds it to the dict file.
    If "check transcription" option is selected, writes list of unknown words to file and exits."""
    ## INPUT:  list of lines to check against CMU dictionary
    ## OUTPUT:  list newlines = list of list of words for each line (processed)
    ## - prompts user to modify CMU dictionary (cmudict) and writes updated version of CMU dictionary to file
    ## - if "check transcription" option is selected, writes list of unknown words to file and exits

    newlines = []
    unknown = {}
    ## "flag_uncertain" indicates whether we are currently inside an uncertain section of transcription
    ## (switched on and off by the beginning or end of double parentheses:  "((", "))")
    flag_uncertain = False
    last_beg_uncertain = ''
    last_end_uncertain = ''

    for line in lines:
        newwords = []
        ## get list of preprocessed words in each line
        ## ("uncertainty flag" has to be passed back and forth because uncertain passages might span more than one breathgroup)
        (words, flag_uncertain, last_beg_uncertain, last_end_uncertain) = preprocess_transcription(line.strip().upper(), flag_uncertain, last_beg_uncertain, last_end_uncertain)
        ## check each word in transcription as to whether it is in the CMU dictionary:
        ## (if "check transcription" option is not set, dict unknown will simply remain empty)
        for i, w in enumerate(words):
            if i < len(words) - 1:
                unknown = check_word(w, words[i+1], unknown, line)
            else:
                unknown = check_word(w, '', unknown, line)               ## last word in line
            ## take "clue words" out of transcription:
            if not intended.search(uncertain.sub(r'\1', w)):
                newwords.append(w)
        newlines.append(newwords)

    ## write new version of the CMU dictionary to file
    ## (do this here so that new entries to dictionary will still be saved if "check transcription" option is selected
    ## in addition to the "import transcriptions" option)
    #write_dict(options.dict)
    ## NOTE:  dict will no longer be re-written to file as people might upload all kinds of junk
    ##        Uploaded additional transcriptions will be written to a separate file instead (in add_dictionary_entries), 
    ##        to be checked manually and merged with the main dictionary at certain intervals

        
    ## write temporary version of the CMU dict to file for use in alignment
    global options  ## need to make options global because dict setting must be changed
    if not options.check:
        global temp_dict
        temp_dict = os.path.join(os.path.dirname(wavfile), '_'.join(os.path.basename(wavfile).split('_')[:2]) + "_" + "dict")
        print "temp_dict is %s." % temp_dict
        write_dict(temp_dict)
        if options.verbose:
            print "Written updated temporary version of CMU dictionary."
        ## forced alignment must use updated cmudict, not original one
        options.dict = temp_dict

    ## "CHECK TRANSCRIPTION" OPTION:
    ## write list of unknown words and suggested transcriptions for truncated words to file
    if options.check:
        write_unknown_words(unknown)            
        print "Written list of unknown words in transcription to file %s." % options.check
        if __name__ == "__main__":
            sys.exit()
            
    ## CONTINUE TO ALIGNMENT:
    else:
        ## return new transcription (list of lists of words, for each line)
        return newlines
    

def check_file(path):
    """checks whether a file exists at a given location and is a data file"""
    
    if os.path.exists(path) and os.path.isfile(path):
        return path
    else:
        if __name__ == "__main__":
            print "ERROR!  File %s could not be found!" % path
            print "Current working directory is %s." % os.getcwd()
            newpath = raw_input("Please enter correct name or path for file, or type [q] to quit:  ")
            ## emergency exit from recursion loop:
            if newpath in ['q', 'Q']:
                sys.exit("Program interrupted by user.")
            else:
                ## re-check...
                checked_path = check_file(newpath)
            return checked_path
        else:
            error = "ERROR!  File %s could not be found!" % path
            errorhandler(error)


def check_phone(p, w, i):
    """checks that a phone entered by the user is part of the Arpabet"""
    ## INPUT:
    ## string p = phone
    ## string w = word the contains the phone (normal orthographic representation)
    ## int i = index of phone in word (starts at 0)
    ## OUTPUT:
    ## string final_p or p = phone in correct format
    
    if not ((len(p) <= 5 and p[-1] in ['0', '1', '2', '3', '4'] and p[:-1] in VOWELS) or (len(p) <= 3 and p in CONSONANTS)):
        ## check whether transcriber didn't simply forget the stress coding for vowels:
        if __name__ == "__main__":
            if len(p) == 2 and p in VOWELS:
                print "You forgot to enter the stress digit for vowel %s (at position %i) in word %s!\n" % (p, i+1, w)
                new_p = raw_input("Please re-enter vowel transcription, or type [q] to quit:  ")
            else:
                print "Unknown phone %s (at position %i) in word %s!\n" % (p, i+1, w)
                new_p = raw_input("Please correct your transcription for this phone, or type [q] to quit:  ")
            ## EMERGENCY EXIT:
            ## (to get out of the loop without having to kill the terminal) 
            if new_p in ['q', 'Q']:
                sys.exit()
            ## check new transcription:
            final_p = check_phone(new_p, w, i)
            return final_p
        else:
            error = "Unknown phone %s (at position %i) in word %s!\n" % (p, i+1, w)
            errorhandler(error)
    else:
        return p


def check_transcription(w):
    """checks that the transcription entered for a word conforms to the Arpabet style"""
    ## INPUT:  string w = phonetic transcription of a word (phones should be separated by spaces)
    ## OUTPUT:  list final_trans = list of individual phones (upper case, checked for correct format)
    
    ## convert to upper case and split into phones
    phones = w.upper().split()
    ## check that phones are separated by spaces
    ## (len(w) > 3:  transcription could just consist of a single phone!)
    if len(w) > 5 and len(phones) < 2:
        print "Something is wrong with your transcription:  %s.\n" % w
        print "Did you forget to enter spaces between individual phones?\n"
        new_trans = raw_input("Please enter new transcription:  ")
        final_trans = check_transcription(new_trans)
    else:
        final_trans = [check_phone(p, w, i) for i, p in enumerate(phones)]
        
    return final_trans

# substitute any 'smart' quotes in the input file with the corresponding
# ASCII equivalents (otherwise they will be excluded as out-of-
# vocabulary with respect to the CMU pronouncing dictionary)
# WARNING: this function currently only works for UTF-8 input
def replace_smart_quotes(all_input):
  cleaned_lines = []
  for line in all_input:
    line = line.replace(u'\u2018', "'")
    line = line.replace(u'\u2019', "'")
    line = line.replace(u'\u201a', "'")
    line = line.replace(u'\u201b', "'")
    line = line.replace(u'\u00B4', "'")
    line = line.replace(u'\u0060', "'")
    line = line.replace(u'\u201c', '"')
    line = line.replace(u'\u201d', '"')
    line = line.replace(u'\u201e', '"')
    line = line.replace(u'\u201f', '"')
    line = line.replace(u'\u00E4', '$')
    line = line.replace(u'\u00F6', '#')
    line = line.replace(u'\u00E5', '@')
    line = line.replace(u'\u00C4', '$')
    line = line.replace(u'\u00D6', '#')
    line = line.replace(u'\u00C5', '@')
    line = line.replace(u'\u00C0', 'A')
    line = line.replace(u'\u00C1', 'A')
    line = line.replace(u'\u00C2', 'A')
    line = line.replace(u'\u00C3', 'A')
    line = line.replace(u'\u00C6', 'AE')
    line = line.replace(u'\u00C7', 'C')
    line = line.replace(u'\u00C8', 'E')
    line = line.replace(u'\u00C9', 'E')
    line = line.replace(u'\u00CA', 'E')
    line = line.replace(u'\u00CB', 'E')
    line = line.replace(u'\u00CC', 'I')
    line = line.replace(u'\u00CD', 'I')
    line = line.replace(u'\u00CE', 'I')
    line = line.replace(u'\u00CF', 'I')
    line = line.replace(u'\u00D0', 'D')
    line = line.replace(u'\u00D1', 'N')
    line = line.replace(u'\u00D2', 'O')
    line = line.replace(u'\u00D3', 'O')
    line = line.replace(u'\u00D4', 'O')
    line = line.replace(u'\u00D5', 'O')
    line = line.replace(u'\u00D7', 'x')
    line = line.replace(u'\u00D8', 'OE')
    line = line.replace(u'\u00D9', 'U')
    line = line.replace(u'\u00DA', 'U')
    line = line.replace(u'\u00DB', 'U')
    line = line.replace(u'\u00DC', 'U')
    line = line.replace(u'\u00DD', 'Y')
    line = line.replace(u'\u00DE', 'T')
    line = line.replace(u'\u00DF', 'ss')
    line = line.replace(u'\u00E0', 'a')
    line = line.replace(u'\u00E1', 'a')
    line = line.replace(u'\u00E2', 'a')
    line = line.replace(u'\u00E3', 'a')
    line = line.replace(u'\u00E6', 'ae')
    line = line.replace(u'\u00E7', 'c')
    line = line.replace(u'\u00E8', 'e')
    line = line.replace(u'\u00E9', 'e')
    line = line.replace(u'\u00EA', 'e')
    line = line.replace(u'\u00EB', 'e')
    line = line.replace(u'\u00EC', 'i')
    line = line.replace(u'\u00ED', 'i')
    line = line.replace(u'\u00EE', 'i')
    line = line.replace(u'\u00EF', 'i')
    line = line.replace(u'\u00F0', 'd')
    line = line.replace(u'\u00F1', 'n')
    line = line.replace(u'\u00F2', 'o')
    line = line.replace(u'\u00F3', 'o')
    line = line.replace(u'\u00F4', 'o')
    line = line.replace(u'\u00F5', 'o')
    line = line.replace(u'\u00F8', 'oe')
    line = line.replace(u'\u00F9', 'u')
    line = line.replace(u'\u00FA', 'u')
    line = line.replace(u'\u00FB', 'u')
    line = line.replace(u'\u00FC', 'u')
    line = line.replace(u'\u00FD', 'y')
    line = line.replace(u'\u00FE', 't')
    line = line.replace(u'\u00FF', 'y')

    cleaned_lines.append(line)
  return cleaned_lines

def check_transcription_file(all_input):
    """checks the format of the input transcription file and returns a list of empty lines to be deleted from the input"""
    trans_lines = []
    delete_lines = []
    for line in all_input:
        t_entries, d_line = check_transcription_format(line)
        if t_entries:
            trans_lines.append(t_entries[4])
        if d_line:
            delete_lines.append(d_line)

    return trans_lines, delete_lines    


def check_transcription_format(line):
    """checks that input format of transcription file is correct (5 tab-delimited data fields)"""
    ## INPUT:  string line = line of transcription file
    ## OUTPUT: list entries = fields in line (speaker ID and name, begin and end times, transcription text)
    ##         string line = empty transcription line to be deleted 
    
    entries = line.rstrip().split('\t')
    ## skip empty lines
    if line.strip():
        if len(entries) != 5:
            ## if there are only 4 fields per line, chances are that the annotation unit is empty and people just forgot to delete it,
            ## which is not worth aborting the program, so continue
            if len(entries) == 4:
                if options.verbose:
                    print "\tWARNING!  Empty annotation unit:  %s" % line.strip()
                return None, line
            else:
                if __name__ == "__main__":
                    print "WARNING:  Incorrect format of input file: %i entries per line." % len(entries)
                    for i in range(len(entries)):
                        print i, "\t", entries[i]
                    stop_program = raw_input("Stop program?  [y/n]")
                    if stop_program == "y":
                        sys.exit("Exiting program.")
                    elif stop_program == "n":
                        print "Continuing program."
                        return None, line
                    else:
                        sys.exit("Undecided user.  Exiting program.")
                else:
                    error = "Incorrect format of transcription file: %i entries per line in line %s." % (len(entries), line.rstrip())
                    raise Exception, error
        else:
            return entries, None
    ## empty line
    else:
        return None, line


def check_word(word, next_word='', unknown={}, line=''):
    """checks whether a given word's phonetic transcription is in the CMU dictionary;
    adds the transcription to the dictionary if not"""
    ## INPUT:                              
    ## string word = word to be checked           
    ## string next_word = following word
    ## OUTPUT:
    ## dict unknown = unknown or truncated words (needed if "check transcription" option is selected; remains empty otherwise)
    ## - modifies CMU dictionary (dict cmudict)
    global cmudict

    clue = ''

    ## dictionary entry for truncated words may exist but not be correct for the current word
    ## (check first because word will be in CMU dictionary after procedure below)
    if truncated.search(word) and word in cmudict:
        ## check whether following word is "clue" word? 
        if intended.search(next_word):
            clue = next_word
        ## do not prompt user for input if "check transcription" option is selected
        ## add truncated word together with its proposed transcription to list of unknown words
        ## (and with following "clue" word, if present)
        if options.check:
            if clue:
                unknown[word] = (cmudict[word], clue.lstrip('+'), line)
            else:
                unknown[word] = (cmudict[word], '', line)
        ## prompt user for input
        else:
            ## assume that truncated words are taken care of by the user if an import file is specified
            ## also, do not prompt user if "noprompt" option is selected
            if not (options.importfile or options.noprompt):
                print "Dictionary entry for truncated word %s is %s." % (word, cmudict[word])
                if clue:
                    print "Following word is %s." % next_word
                correct = raw_input("Is this correct?  [y/n]")
                if correct != "y":
                    transcription = prompt_user(word, clue) 
                    cmudict[word] = [transcription]
    
    elif word not in cmudict and word not in STYLE_ENTRIES:
        ## truncated words:
        if truncated.search(word):
            ## is following word "clue" word?  (starts with "+")
            if intended.search(next_word):
                clue = next_word
        ## don't do anything if word itself is a clue word
        elif intended.search(word):
            return unknown
        ## don't do anything for unclear transcriptions:
        elif word == '((xxxx))':
            return unknown
        ## uncertain transcription:
        elif start_uncertain.search(word) or end_uncertain.search(word):
            if start_uncertain.search(word) and end_uncertain.search(word):
                word = word.replace('((', '')
                word = word.replace('))', '')
                ## check if word is in dictionary without the parentheses
                check_word(word, '', unknown, line)
                return unknown
            else:  ## This should not happen!
                error= "ERROR!  Something is wrong with the transcription of word %s!" % word
                errorhandler(error)
        ## asterisked transcriptions:
        elif word and word[0] == "*":
            ## check if word is in dictionary without the asterisk
            check_word(word[1:], '', unknown, line)
            return unknown
        ## generate new entries for "-in'" words
        if ing.search(word):
            gword = ing.sub("ING", word)
            ## if word has entry/entries for corresponding "-ing" form:
            if gword in cmudict:
                for t in cmudict[gword]:
                    ## check that transcription entry ends in "- IH0 NG":
                    if t[-1] == "NG" and t[-2] == "IH0":
                        tt = t
                        tt[-1] = "N"
                        tt[-2] = "AH0"
                        if word not in cmudict:
                            cmudict[word] = [tt]
                        else:
                            cmudict[word].append(tt)
                return unknown
        ## if "check transcription" option is selected, add word to list of unknown words
        if options.check:
            if clue:
                unknown[word] = ("", clue.lstrip('+'), line)
            else:
                unknown[word] = ("", "", line)
            if options.verbose:
                print "\tUnknown word %s : %s." % (word.encode('ascii', 'replace'), line.encode('ascii', 'replace'))

        ## otherwise, promput user for Arpabet transcription of missing word
        elif not options.noprompt:
            transcription = prompt_user(word, clue)
            ## add new transcription to dictionary
            if transcription:  ## user might choose to skip this word
                cmudict[word] = [transcription]

    return unknown


def cut_chunk(wavfile, outfile, start, dur, SOXPATH):
    """uses SoX to cut a portion out of a sound file"""
    
    if SOXPATH:
        command_cut_sound = " ".join([SOXPATH, '\"' + wavfile + '\"', '\"' + outfile + '\"', "trim", str(start), str(dur)])
        ## ("sox <original sound file> "<new sound chunk>" trim <start of selection (in sec)> <duration of selection (in sec)>")
        ## (put file paths into quotation marks to accomodate special characters (spaces, parantheses etc.))
    else:
        command_cut_sound = " ".join(["sox", '\"' + wavfile + '\"', '\"' + outfile + '\"', "trim", str(start), str(dur)])
    try:
        os.system(command_cut_sound)
        if options.verbose:
            print "\tSound chunk %s successfully extracted." % (outfile) #os.path.basename(outfile)
    except Exception, e:
        sound_error = "Error in extracting sound chunk %s:  %s." % (os.path.basename(outfile), e)
        errorhandler(sound_error)


def define_options_and_arguments():
    """defines options and positional arguments for this program"""
    
    use = """(python) %prog [options] soundfile.wav [transcription.txt] [output.TextGrid]"""
    desc = """Aligns a sound file with the corresponding transcription text. The transcription text is split into annotation breath groups, which are fed individually as "chunks" to the forced aligner. All output is concatenated into a single Praat TextGrid file. 

    INPUT:
    - sound file
    - tab-delimited text file with the following columns:
        first column:   speaker ID
        second column:  speaker name
        third column:   beginning of breath group (in seconds)
        fourth column:  end of breath group (in seconds)
        fifth column:   transcribed text
    (If no name is specified for the transcription file, it will be assumed to have the same name as the sound file, plus ".txt" extension.)

    OUTPUT:
    - Praat TextGrid file with orthographic and phonemic transcription tiers for each speaker (If no name is specified, it will be given same name as the sound file, plus ".TextGrid" extension.)"""

    ep = """The following additional programs need to be installed and in the path:
    - Praat (on Windows machines, the command line version praatcon.exe)
    - SoX"""

    vers = """This is %prog, a new version of align.py, written by Jiahong Yuan, combining it with Ingrid Rosenfelder's front_end_FA.py and an interactive CMU dictionary check for all words in the transcription file.
    Last modified May 14, 2010."""

    new_use = format_option_text(use)
    new_desc = format_option_text(desc)
    new_ep = format_option_text(ep)

    check_help = """Checks whether phonetic transcriptions for all words in the transcription file can be found in the CMU Pronouncing Dictionary.  Returns a list of unknown words (required argument "FILENAME")."""
    import_help = """Adds a list of unknown words and their corresponding phonetic transcriptions to the CMU Pronouncing Dictionary prior to alignment.  User will be prompted interactively for the transcriptions of any remaining unknown words.  Required argument "FILENAME" must be tab-separated plain text file (one word - phonetic transcription pair per line)."""
    verbose_help = """Detailed output on status of dictionary check and alignment progress."""
    dict_help = """Specifies the name of the file containing the pronunciation dictionary.  Default file is "/model/dict"."""
    noprompt_help = """User is not prompted for the transcription of words not in the dictionary, or truncated words.  Unknown words are ignored by the aligner."""
    htktoolspath_help = """Specifies the path to the HTKTools directory where the HTK executable files are located.  If not specified, the user's path will be searched for the location of the executable."""

    parser = optparse.OptionParser(usage=new_use, description=new_desc, epilog=new_ep, version=vers)
    parser.add_option('-c', '--check', help=check_help, metavar='FILENAME')                        ## required argument FILENAME
    parser.add_option('-i', '--import', help=import_help, metavar='FILENAME', dest='importfile')   ## required argument FILENAME
    parser.add_option('-v', '--verbose', action='store_true', default=False, help=verbose_help)
    parser.add_option('-d', '--dict', default='model/dict', help=dict_help, metavar='FILENAME')
    parser.add_option('-n', '--noprompt', action='store_true', default=False, help=noprompt_help)
    parser.add_option('-t', '--htktoolspath', default='', help=htktoolspath_help, metavar='HTKTOOLSPATH')

    ## After parsing with (options, args) = parser.parse_args(), options are accessible via
    ## - string options.check (default:  None)
    ## - string options.importfile (default:  None)
    ## - "bool" options.verbose (default:  False)
    ## - string options.dict (default:  "model/dict")
    ## - "bool" options.noprompt (default:  False)

    return parser


def delete_empty_lines(delete_lines, all_input):
    """deletes empty lines from the original input (this is important to match up the original and processed transcriptions later)"""

    #print "Lines to be deleted (%s):  %s" % (len(delete_lines), delete_lines)
    #print "Original input is %d lines long." % len(all_input)
    p = 0  ## use pointer to mark current position in original input (to speed things up a little)
    for dline in delete_lines:
        d = dline.split('\t')
        ## reset pointer p if we have run unsuccessfully through the whole input for the previous dline
        if p == len(all_input):
            p = 0
        while p < len(all_input):
            ## go through the original input lines until we find the line to delete
            o = all_input[p].split('\t')
            ## first four fields (speaker ID, speaker name, beginning and end of annotation unit) have to agree
            ## otherwise, the problem is not caused by an empty annotation unit
            ## and the program should terminate with an error
            ## (not o[0].strip():  delete completely empty lines as well!)
            if (len(o) >= 4 and (o[0] == d[0]) and (o[1] == d[1]) and (o[2] == d[2]) and (o[3] == d[3])) or not o[0].strip():
                all_input.pop(p)
                ## get out of the loop
                break
            p += 1

    #print "Input is now %d lines long." % len(all_input)
    if options.verbose:
        print "Deleted empty lines from original transcription file."

    return all_input
        

def errorhandler(errormessage):
    """handles the error depending on whether the file is run as a standalone or as an imported module"""
    
    if __name__ == "__main__":  ## file run as standalone program
        sys.exit(errormessage)
    else:  ## run as imported module from somewhere else -> propagate exception
        raise Exception, errormessage
    

def format_option_text(text):
    """re-formats usage, description and epiloge strings for the OptionParser
    so that they do not get mangled by optparse's textwrap"""
    ## NOTE:  This is a (pretty ugly) hack to (partially) preserve newline characters
    ## in the description strings for the OptionParser.
    ## "textwrap" appears to preserve (non-initial) spaces, so all lines containing newlines
    ## are padded with spaces until they reach the length of 80 characters,
    ## which is the width to which "textwrap" formats the description text.
    
    lines = text.split('\n')
    newlines = ''
    for line in lines:
        ## pad remainder of line with spaces
        n, m = divmod(len(line), 80)
        if m != 0:
            line += (' ' * (80 - m))
        newlines += line
        
    return newlines


def get_duration(soundfile, FADIR=''):
    """gets the overall duration of a soundfile"""
    ## INPUT:  string soundfile = name of sound file
    ## OUTPUT:  float duration = duration of sound file

    try:
        ## calculate duration by sampling rate and number of frames
        f = wave.open(soundfile, 'r')
        sr = float(f.getframerate())
        nx = f.getnframes()
        f.close()
        duration = round((nx / sr), 3)
    except wave.Error:  ## wave.py does not seem to support 32-bit .wav files???
        if PRAATPATH:
            dur_command = "%s %s %s" % (PRAATPATH, os.path.join(FADIR, "get_duration.praat"), soundfile)
        else:
            dur_command = "praat %s %s" % (os.path.join(FADIR, "get_duration.praat"), soundfile)
        duration = round(float(subprocess.Popen(dur_command, shell=True, stdout=subprocess.PIPE).communicate()[0].strip()), 3)
    
    return duration
    

def is_sound(f):
    """checks whether a file is a .wav sound file"""
    
    if f.lower().endswith('.wav'):
## NOTE:  This is the old version of the file check using a call to 'file' via the command line
##    and ("audio/x-wav" in subprocess.Popen('file -bi "%s"' % f, shell=True, stdout=subprocess.PIPE).communicate()[0].strip()
##                                           or "audio/x-wav" in subprocess.Popen('file -bI "%s"' % f, shell=True, stdout=subprocess.PIPE).communicate()[0].strip()):
##    ## NOTE:  "file" options:
##    ##          -b      brief (no filenames appended)
##    ##          -i/-I   outputs MIME file types (capital letter or not different for different versions)
        return True
    else:
        return False


def is_text(f):
    """checks whether a file is a .txt text file"""
    
    if f.lower().endswith('.txt'):
## NOTE:  This is the old version of the file check using a call to 'file' via the command line
##    and ("text/plain" in subprocess.Popen('file -bi "%s"' % f, shell=True, stdout=subprocess.PIPE).communicate()[0].strip()
##                                           or "text/plain" in subprocess.Popen('file -bI "%s"' % f, shell=True, stdout=subprocess.PIPE).communicate()[0].strip()):
        return True
    else:
        return False


def is_TextGrid(f):
    """checks whether a file is a .TextGrid file"""
    
    if re.search("\.TextGrid$", f):  ## do not test the actual file type because file does not yet exist at this point!
        return True
    else:
        return False


# def make_tempdir(tempdir):
#     """creates a temporary directory for all alignment "chunks";
#     warns against overwriting existing files if applicable"""
    
#     ## check whether directory already exists and has files in it
#     if os.path.isdir(tempdir):
#         contents = os.listdir(tempdir)
#         if len(contents) != 0 and not options.noprompt:
#             print "WARNING!  Directory %s already exists and is non-empty!" % tempdir
#             print "(Files in directory:  %s )" % contents
#             overwrite = raw_input("Overwrite and continue?  [y/n]")
#             if overwrite == "y":
#                 ## delete contents of tempdir
#                 for item in contents:
#                     os.remove(os.path.join(tempdir, item))
#             elif overwrite == "n":
#                 sys.exit("Exiting program.")
#             else:
#                 sys.exit("Undecided user.  Exiting program.")
#     else:
#         os.mkdir(tempdir)


def check_tempdir(tempdir):
    """checks that the temporary directory for all alignment "chunks" is empty"""
    
    ## (NOTE:  This is a modified version of make_tempdir)
    ## check whether directory already exists and has files in it
    if os.path.isdir(tempdir):
        contents = os.listdir(tempdir)
        if len(contents) != 0 and not options.noprompt:
            print "WARNING!  Directory %s is non-empty!" % tempdir
            print "(Files in directory:  %s )" % contents
            overwrite = raw_input("Overwrite and continue?  [y/n]")
            if overwrite == "y":
                ## delete contents of tempdir
                for item in contents:
                    os.remove(os.path.join(tempdir, item))
            elif overwrite == "n":
                sys.exit("Exiting program.")
            else:
                sys.exit("Undecided user.  Exiting program.")


def mark_time(index):
    """generates a time stamp entry in global list times[]"""
    
    cpu_time = time.clock()
    real_time = time.time()
    times.append((index, cpu_time, real_time))


def merge_dicts(d1, d2):
    """merges two versions of the CMU pronouncing dictionary"""
    ## for each word, each transcription in d2, check if present in d1
    for word in d2:
        ## if no entry in d1, add entire entry 
        if word not in d1:
            d1[word] = d2[word]
        ## if entry in d1, check whether additional transcription variants need to be added
        else:
            for t in d2[word]:
                if t not in d1[word]:
                    d1[word].append(t)
    return d1


def merge_textgrids(main_textgrid, new_textgrid, speaker, chunkname_textgrid):
    """adds the contents of TextGrid new_textgrid to TextGrid main_textgrid"""
    
    for tier in new_textgrid:
        ## change tier names to reflect speaker names
        ## (output of FA program is "phone", "word" -> "Speaker - phone", "Speaker - word")
        tier.rename(speaker + " - " + tier.name())
        ## check if tier already exists:
        exists = False
        for existing_tier in main_textgrid:
            if tier.name() == existing_tier.name():
                exists = True
                break   ## need this so existing_tier retains its value!!!
        if exists:
            for interval in tier:
                existing_tier.append(interval)
        else:
            main_textgrid.append(tier)
    if options.verbose:
        print "\tSuccessfully added", chunkname_textgrid, "to main TextGrid."
        
    return main_textgrid


def preprocess_transcription(line, flag_uncertain, last_beg_uncertain, last_end_uncertain):
    """preprocesses transcription input for CMU dictionary lookup and forced alignment"""
    ## INPUT:  string line = line of orthographic transcription
    ## OUTPUT:  list words = list of individual words in transcription
    
    original_line = line

    ## correct common misspellings
    line = line.replace('lungt', 'lugnt')
    line = line.replace('tjugio', 'tjugo')
    line = line.replace('shuno', 'shunno')
    line = line.replace('shunne', 'shunno')
    line = line.replace('shonno', 'shunno')
    line = line.replace('$ttrig', 'ettrig')
    line = line.replace('abow', 'abo')
    line = line.replace('aboow', 'abo')
    line = line.replace('approp@', 'aprop@')
    line = line.replace('branch', 'bransch')
    line = line.replace('dommar', 'domar')
    line = line.replace('fake ', 'fejk ')
    line = line.replace('jao', 'yao')
    line = line.replace('llition', 'lition')
    line = line.replace('koallision', 'koalition')
    line = line.replace('y$ni', 'yani')
    line = line.replace('zinkensdam ', 'zinkensdamm ')
    line = line.replace('pl#stlig', 'pl#tslig')
    line = line.replace('statshagen', 'stadshagen')
    line = line.replace('anden {duck}', 'anden1')
    line = line.replace('anden {genie}', 'anden2')

    ## make beginning and end of uncertain transcription spans into separate words
    line = start_uncertain.sub(r' (( ', line)
    line = end_uncertain.sub(r' )) ', line)   
    ## correct a common transcription error (one dash instead of two)
    line = line.replace(' - ', ' -- ')
    ## delete punctuation marks
    for p in [',', '.', ':', ';', '!', '?', '"', '%', '--']:
        line = line.replace(p, ' ')
    ## delete initial apostrophes
    line = re.compile(r"(\s|^)'\b").sub(" ", line)
    ## delete variable coding for consonant cluster reduction
    line = re.compile(r"\d\w(\w)?").sub(" ", line)
    ## replace unclear transcription markup (empty parentheses):
    line = unclear.sub('((xxxx))', line)
    ## correct another transcription error:  truncation dash outside of double parentheses will become a word
    line = line.replace(' - ', '')
    
    ## Tonal sandhi effects for, primarily, verbs
    line = line.replace(' @ EN ', ' @_EN ')
    line = line.replace(' @ ETT ', ' @_ETT ')
    line = line.replace(' @B$KA SIG ', ' @B$KA_SIG ')
    line = line.replace(' @DRAGA SIG ', ' @DRAGA_SIG ')
    line = line.replace(' @KA FAST ', ' @KA_FAST ')
    line = line.replace(' @KA IN ', ' @KA_IN ')
    line = line.replace(' @KA MED ', ' @KA_MED ')
    line = line.replace(' @KA UPP ', ' @KA_UPP ')
    line = line.replace(' @KA UT ', ' @KA_UT ')
    line = line.replace(' @KERS STYCKEBRUK ', ' @KERS_STYCKEBRUK ')
    line = line.replace(' @KERS STYCKEBRUKS ', ' @KERS_STYCKEBRUKS ')
    line = line.replace(' @L$GGA SIG ', ' @L$GGA_SIG ')
    line = line.replace(' @LA SIG FRAM ', ' @LA_SIG_FRAM ')
    line = line.replace(' @MA SIG ', ' @MA_SIG ')
    line = line.replace(' @NGRA SIG ', ' @NGRA_SIG ')
    line = line.replace(' @TA SIG ', ' @TA_SIG ')
    line = line.replace(' @TAGA SIG ', ' @TAGA_SIG ')
    line = line.replace(' @TERF#RS$KRA SIG ', ' @TERF#RS$KRA_SIG ')
    line = line.replace(' @TERH$MTA SIG ', ' @TERH$MTA_SIG ')
    line = line.replace(' @TRA SIG ', ' @TRA_SIG ')
    line = line.replace(' #DMJUKA SIG ', ' #DMJUKA_SIG ')
    line = line.replace(' #GLA SIG ', ' #GLA_SIG ')
    line = line.replace(' #GNA IGENOM ', ' #GNA_IGENOM ')
    line = line.replace(' #KA P@ ', ' #KA_P@ ')
    line = line.replace(' #KA UT ', ' #KA_UT ')
    line = line.replace(' #MKA SIG ', ' #MKA_SIG ')
    line = line.replace(' #NSKA SIG ', ' #NSKA_SIG ')
    line = line.replace(' #PPNA SIG ', ' #PPNA_SIG ')
    line = line.replace(' #PPNA UPP ', ' #PPNA_UPP ')
    line = line.replace(' #RBY SLOTTSV$G ', ' #RBY_SLOTTSV$G ')
    line = line.replace(' #SA #VER ', ' #SA_#VER ')
    line = line.replace(' #SA I ', ' #SA_I ')
    line = line.replace(' #SA UPP ', ' #SA_UPP ')
    line = line.replace(' #SA UT ', ' #SA_UT ')
    line = line.replace(' #STRA FR#LUNDA ', ' #STRA_FR#LUNDA ')
    line = line.replace(' #STRA KARUP ', ' #STRA_KARUP ')
    line = line.replace(' #STRA LJUNGBY ', ' #STRA_LJUNGBY ')
    line = line.replace(' #STRA RYD ', ' #STRA_RYD ')
    line = line.replace(' #STRA S#NNARSL#V ', ' #STRA_S#NNARSL#V ')
    line = line.replace(' #VA IN ', ' #VA_IN ')
    line = line.replace(' #VA SIG ', ' #VA_SIG ')
    line = line.replace(' #VA UPP ', ' #VA_UPP ')
    line = line.replace(' #VERANSTR$NGA SIG ', ' #VERANSTR$NGA_SIG ')
    line = line.replace(' #VERILA SIG ', ' #VERILA_SIG ')
    line = line.replace(' $GNA SIG ', ' $GNA_SIG ')
    line = line.replace(' $LVANS V$G ', ' $LVANS_V$G ')
    line = line.replace(' $MNA SIG ', ' $MNA_SIG ')
    line = line.replace(' $NDRA SIG ', ' $NDRA_SIG ')
    line = line.replace(' $NGSLA SIG ', ' $NGSLA_SIG ')
    line = line.replace(' $RGA SIG ', ' $RGA_SIG ')
    line = line.replace(' $RNA SIG ', ' $RNA_SIG ')
    line = line.replace(' $RRA SIG ', ' $RRA_SIG ')
    line = line.replace(' $TA SIG M$TT ', ' $TA_SIG_M$TT ')
    line = line.replace(' $TA UPP ', ' $TA_UPP ')
    line = line.replace(' A JOUR ', ' A_JOUR ')
    line = line.replace(' A LA ', ' A_LA ')
    line = line.replace(' A LA CARTE ', ' A_LA_CARTE ')
    line = line.replace(' ABSENTERA SIG ', ' ABSENTERA_SIG ')
    line = line.replace(' ABSTRAHERA FRAM ', ' ABSTRAHERA_FRAM ')
    line = line.replace(' ACKLIMATISERA SIG ', ' ACKLIMATISERA_SIG ')
    line = line.replace(' AD HOC ', ' AD_HOC ')
    line = line.replace(' AD NOTAM ', ' AD_NOTAM ')
    line = line.replace(' ADRESSERA SIG ', ' ADRESSERA_SIG ')
    line = line.replace(' AJA SIG ', ' AJA_SIG ')
    line = line.replace(' AKTA SIG ', ' AKTA_SIG ')
    line = line.replace(' AL PARI ', ' AL_PARI ')
    line = line.replace(' ALIENERA SIG ', ' ALIENERA_SIG ')
    line = line.replace(' ALL ROUND ', ' ALL_ROUND ')
    line = line.replace(' ALLIERA SIG ', ' ALLIERA_SIG ')
    line = line.replace(' ALLM$NBILDA SIG ', ' ALLM$NBILDA_SIG ')
    line = line.replace(' ALMA MATER ', ' ALMA_MATER ')
    line = line.replace(' ALTER EGO ', ' ALTER_EGO ')
    line = line.replace(' AMORTERA NED ', ' AMORTERA_NED ')
    line = line.replace(' ANALYSERA FRAM ', ' ANALYSERA_FRAM ')
    line = line.replace(' ANDAS IN ', ' ANDAS_IN ')
    line = line.replace(' ANDAS UT ', ' ANDAS_UT ')
    line = line.replace(' ANF#RTRO SIG ', ' ANF#RTRO_SIG ')
    line = line.replace(' ANKRA UPP ', ' ANKRA_UPP ')
    line = line.replace(' ANM$LA SIG ', ' ANM$LA_SIG ')
    line = line.replace(' ANSAMLA SIG ', ' ANSAMLA_SIG ')
    line = line.replace(' ANSLUTA SIG ', ' ANSLUTA_SIG ')
    line = line.replace(' ANTECKNA SIG ', ' ANTECKNA_SIG ')
    line = line.replace(' ANV$NDA SIG AV ', ' ANV$NDA_SIG_AV ')
    line = line.replace(' APA EFTER ', ' APA_EFTER ')
    line = line.replace(' APA SIG ', ' APA_SIG ')
    line = line.replace(' ARBETA #VER ', ' ARBETA_#VER ')
    line = line.replace(' ARBETA AV ', ' ARBETA_AV ')
    line = line.replace(' ARBETA EMOT ', ' ARBETA_EMOT ')
    line = line.replace(' ARBETA FRAM ', ' ARBETA_FRAM ')
    line = line.replace(' ARBETA I ', ' ARBETA_I ')
    line = line.replace(' ARBETA IGENOM ', ' ARBETA_IGENOM ')
    line = line.replace(' ARBETA IHOP ', ' ARBETA_IHOP ')
    line = line.replace(' ARBETA IN ', ' ARBETA_IN ')
    line = line.replace(' ARBETA OM ', ' ARBETA_OM ')
    line = line.replace(' ARBETA SAMMAN ', ' ARBETA_SAMMAN ')
    line = line.replace(' ARBETA UNDAN ', ' ARBETA_UNDAN ')
    line = line.replace(' ARBETA UPP ', ' ARBETA_UPP ')
    line = line.replace(' ARBETA UT ', ' ARBETA_UT ')
    line = line.replace(' ARRENDERA BORT ', ' ARRENDERA_BORT ')
    line = line.replace(' ARRENDERA UT ', ' ARRENDERA_UT ')
    line = line.replace(' ARTA SIG ', ' ARTA_SIG ')
    line = line.replace(' ASSOCIERA SIG ', ' ASSOCIERA_SIG ')
    line = line.replace(' AU NATURELL ', ' AU_NATURELL ')
    line = line.replace(' AU PAIR ', ' AU_PAIR ')
    line = line.replace(' AU PAIREN ', ' AU_PAIREN ')
    line = line.replace(' AU PAIRENS ', ' AU_PAIRENS ')
    line = line.replace(' AU PAIRER ', ' AU_PAIRER ')
    line = line.replace(' AU PAIRERNA ', ' AU_PAIRERNA ')
    line = line.replace(' AU PAIRERNAS ', ' AU_PAIRERNAS ')
    line = line.replace(' AU PAIRERS ', ' AU_PAIRERS ')
    line = line.replace(' AU PAIRS ', ' AU_PAIRS ')
    line = line.replace(' AUKTIONERA BORT ', ' AUKTIONERA_BORT ')
    line = line.replace(' AV OCH AN ', ' AV_OCH_AN ')
    line = line.replace(' AV OCH TILL ', ' AV_OCH_TILL ')
    line = line.replace(' AVB#RDA SIG ', ' AVB#RDA_SIG ')
    line = line.replace(' AVGR$NSA SIG ', ' AVGR$NSA_SIG ')
    line = line.replace(' AVGRENA SIG ', ' AVGRENA_SIG ')
    line = line.replace(' AVH@LLA SIG ', ' AVH@LLA_SIG ')
    line = line.replace(' AVH$NDA SIG ', ' AVH$NDA_SIG ')
    line = line.replace(' AVLAGRA SIG ', ' AVLAGRA_SIG ')
    line = line.replace(' AVREAGERA SIG ', ' AVREAGERA_SIG ')
    line = line.replace(' AVS$GA SIG ', ' AVS$GA_SIG ')
    line = line.replace(' AVS$TTA SIG ', ' AVS$TTA_SIG ')
    line = line.replace(' AVSK$RMA SIG ', ' AVSK$RMA_SIG ')
    line = line.replace(' AVSKUGGA SIG ', ' AVSKUGGA_SIG ')
    line = line.replace(' AVSV$RA SIG ', ' AVSV$RA_SIG ')
    line = line.replace(' AVTECKNA SIG ', ' AVTECKNA_SIG ')
    line = line.replace(' B#JA AV ', ' B#JA_AV ')
    line = line.replace(' B#JA IN ', ' B#JA_IN ')
    line = line.replace(' B#JA NED ', ' B#JA_NED ')
    line = line.replace(' B#JA SIG ', ' B#JA_SIG ')
    line = line.replace(' B#JA TILL ', ' B#JA_TILL ')
    line = line.replace(' B#JA UNDAN ', ' B#JA_UNDAN ')
    line = line.replace(' B#JA UT ', ' B#JA_UT ')
    line = line.replace(' B#KA UPP ', ' B#KA_UPP ')
    line = line.replace(' B#LJA FRAM ', ' B#LJA_FRAM ')
    line = line.replace(' B#RJA OM ', ' B#RJA_OM ')
    line = line.replace(' B$DDA IN ', ' B$DDA_IN ')
    line = line.replace(' B$DDA NER ', ' B$DDA_NER ')
    line = line.replace(' B$LGA I SIG ', ' B$LGA_I_SIG ')
    line = line.replace(' B$NDA LOSS ', ' B$NDA_LOSS ')
    line = line.replace(' B$NDA UPP ', ' B$NDA_UPP ')
    line = line.replace(' B$NKA SIG ', ' B$NKA_SIG ')
    line = line.replace(' B$RA AV ', ' B$RA_AV ')
    line = line.replace(' B$RA BORT ', ' B$RA_BORT ')
    line = line.replace(' B$RA EMOT ', ' B$RA_EMOT ')
    line = line.replace(' B$RA FRAM ', ' B$RA_FRAM ')
    line = line.replace(' B$RA HEM ', ' B$RA_HEM ')
    line = line.replace(' B$RA HIT ', ' B$RA_HIT ')
    line = line.replace(' B$RA IKRING ', ' B$RA_IKRING ')
    line = line.replace(' B$RA IN ', ' B$RA_IN ')
    line = line.replace(' B$RA IV$G ', ' B$RA_IV$G ')
    line = line.replace(' B$RA NED ', ' B$RA_NED ')
    line = line.replace(' B$RA OMKULL ', ' B$RA_OMKULL ')
    line = line.replace(' B$RA OPP ', ' B$RA_OPP ')
    line = line.replace(' B$RA P@ SIG ', ' B$RA_P@_SIG ')
    line = line.replace(' B$RA SIG ', ' B$RA_SIG ')
    line = line.replace(' B$RA SIG @T ', ' B$RA_SIG_@T ')
    line = line.replace(' B$RA TILL ', ' B$RA_TILL ')
    line = line.replace(' B$RA UNDAN ', ' B$RA_UNDAN ')
    line = line.replace(' B$RA UPP ', ' B$RA_UPP ')
    line = line.replace(' B$RA UT ', ' B$RA_UT ')
    line = line.replace(' B$RA UTF#R ', ' B$RA_UTF#R ')
    line = line.replace(' B$RGA SIG ', ' B$RGA_SIG ')
    line = line.replace(' B$TTRA P@ ', ' B$TTRA_P@ ')
    line = line.replace(' B$TTRA SIG ', ' B$TTRA_SIG ')
    line = line.replace(' BACKA IN ', ' BACKA_IN ')
    line = line.replace(' BACKA UNDAN ', ' BACKA_UNDAN ')
    line = line.replace(' BACKA UPP ', ' BACKA_UPP ')
    line = line.replace(' BACKA UR ', ' BACKA_UR ')
    line = line.replace(' BACKA UT ', ' BACKA_UT ')
    line = line.replace(' BAKA IGENOM ', ' BAKA_IGENOM ')
    line = line.replace(' BAKA IN ', ' BAKA_IN ')
    line = line.replace(' BAKA UT ', ' BAKA_UT ')
    line = line.replace(' BALA NED ', ' BALA_NED ')
    line = line.replace(' BALA SIG ', ' BALA_SIG ')
    line = line.replace(' BALKA AV ', ' BALKA_AV ')
    line = line.replace(' BANA SIG FRAM ', ' BANA_SIG_FRAM ')
    line = line.replace(' BANA V$G ', ' BANA_V$G ')
    line = line.replace(' BANKA IN ', ' BANKA_IN ')
    line = line.replace(' BANKA P@ ', ' BANKA_P@ ')
    line = line.replace(' BANTA NED ', ' BANTA_NED ')
    line = line.replace(' BARKA AV ', ' BARKA_AV ')
    line = line.replace(' BARKA H$N ', ' BARKA_H$N ')
    line = line.replace(' BARKA IV$G ', ' BARKA_IV$G ')
    line = line.replace(' BARRA AV SIG ', ' BARRA_AV_SIG ')
    line = line.replace(' BARRIKADERA SIG ', ' BARRIKADERA_SIG ')
    line = line.replace(' BASUNA UT ', ' BASUNA_UT ')
    line = line.replace(' BASUNERA UT ', ' BASUNERA_UT ')
    line = line.replace(' BAXA UPP ', ' BAXA_UPP ')
    line = line.replace(' BEBLANDA SIG ', ' BEBLANDA_SIG ')
    line = line.replace(' BECKA IGEN ', ' BECKA_IGEN ')
    line = line.replace(' BECKA IHOP ', ' BECKA_IHOP ')
    line = line.replace(' BECKA SIG ', ' BECKA_SIG ')
    line = line.replace(' BEDR#VA SIG ', ' BEDR#VA_SIG ')
    line = line.replace(' BEDRA SIG ', ' BEDRA_SIG ')
    line = line.replace(' BEDRAGA SIG ', ' BEDRAGA_SIG ')
    line = line.replace(' BEFALLA FRAM ', ' BEFALLA_FRAM ')
    line = line.replace(' BEFATTA SIG ', ' BEFATTA_SIG ')
    line = line.replace(' BEFINNA SIG ', ' BEFINNA_SIG ')
    line = line.replace(' BEFLITA SIG ', ' BEFLITA_SIG ')
    line = line.replace(' BEFRIA SIG ', ' BEFRIA_SIG ')
    line = line.replace(' BEFRYNDA SIG ', ' BEFRYNDA_SIG ')
    line = line.replace(' BEG$RA @TER ', ' BEG$RA_@TER ')
    line = line.replace(' BEG$RA FRAM ', ' BEG$RA_FRAM ')
    line = line.replace(' BEG$RA IGEN ', ' BEG$RA_IGEN ')
    line = line.replace(' BEG$RA IN ', ' BEG$RA_IN ')
    line = line.replace(' BEG$RA TILLBAKA ', ' BEG$RA_TILLBAKA ')
    line = line.replace(' BEG$RA UT ', ' BEG$RA_UT ')
    line = line.replace(' BEGAGNA SIG AV ', ' BEGAGNA_SIG_AV ')
    line = line.replace(' BEGE SIG ', ' BEGE_SIG ')
    line = line.replace(' BEGE SIG AV ', ' BEGE_SIG_AV ')
    line = line.replace(' BEGE SIG BORT ', ' BEGE_SIG_BORT ')
    line = line.replace(' BEGE SIG IN ', ' BEGE_SIG_IN ')
    line = line.replace(' BEGE SIG UT ', ' BEGE_SIG_UT ')
    line = line.replace(' BEGIVA SIG ', ' BEGIVA_SIG ')
    line = line.replace(' BEGIVA SIG AV ', ' BEGIVA_SIG_AV ')
    line = line.replace(' BEGR$NSA SIG ', ' BEGR$NSA_SIG ')
    line = line.replace(' BEGRAVA SIG ', ' BEGRAVA_SIG ')
    line = line.replace(' BEGRIPA SIG P@ ', ' BEGRIPA_SIG_P@ ')
    line = line.replace(' BEH@LLA KVAR ', ' BEH@LLA_KVAR ')
    line = line.replace(' BEH@LLA P@ ', ' BEH@LLA_P@ ')
    line = line.replace(' BEK$NNA SIG ', ' BEK$NNA_SIG ')
    line = line.replace(' BEKANTA SIG ', ' BEKANTA_SIG ')
    line = line.replace(' BEKANTG#RA SIG ', ' BEKANTG#RA_SIG ')
    line = line.replace(' BEKLAGA SIG ', ' BEKLAGA_SIG ')
    line = line.replace(' BEKV$MA SIG ', ' BEKV$MA_SIG ')
    line = line.replace(' BEKYMRA SIG ', ' BEKYMRA_SIG ')
    line = line.replace(' BEL#PA SIG TILL ', ' BEL#PA_SIG_TILL ')
    line = line.replace(' BEM#DA SIG ', ' BEM#DA_SIG ')
    line = line.replace(' BEM$KTIGA SIG ', ' BEM$KTIGA_SIG ')
    line = line.replace(' BENA UPP ', ' BENA_UPP ')
    line = line.replace(' BENA UT ', ' BENA_UT ')
    line = line.replace(' BEREDA SIG ', ' BEREDA_SIG ')
    line = line.replace(' BERUSA SIG ', ' BERUSA_SIG ')
    line = line.replace(' BESINNA SIG ', ' BESINNA_SIG ')
    line = line.replace(' BESK$RMA SIG ', ' BESK$RMA_SIG ')
    line = line.replace(' BESPARA SIG ', ' BESPARA_SIG ')
    line = line.replace(' BESPETSA SIG ', ' BESPETSA_SIG ')
    line = line.replace(' BEST$MMA SIG ', ' BEST$MMA_SIG ')
    line = line.replace(' BESV$RA SIG ', ' BESV$RA_SIG ')
    line = line.replace(' BET$NKA SIG ', ' BET$NKA_SIG ')
    line = line.replace(' BETA AV ', ' BETA_AV ')
    line = line.replace(' BETA I ', ' BETA_I ')
    line = line.replace(' BETA P@ ', ' BETA_P@ ')
    line = line.replace(' BETACKA SIG ', ' BETACKA_SIG ')
    line = line.replace(' BETALA AV ', ' BETALA_AV ')
    line = line.replace(' BETALA IN ', ' BETALA_IN ')
    line = line.replace(' BETALA SIG ', ' BETALA_SIG ')
    line = line.replace(' BETALA UT ', ' BETALA_UT ')
    line = line.replace(' BETE SIG ', ' BETE_SIG ')
    line = line.replace(' BETINGA SIG ', ' BETINGA_SIG ')
    line = line.replace(' BETJ$NA SIG ', ' BETJ$NA_SIG ')
    line = line.replace(' BIKTA SIG ', ' BIKTA_SIG ')
    line = line.replace(' BILDA SIG ', ' BILDA_SIG ')
    line = line.replace(' BINDA IHOP ', ' BINDA_IHOP ')
    line = line.replace(' BINDA IN ', ' BINDA_IN ')
    line = line.replace(' BINDA UPP ', ' BINDA_UPP ')
    line = line.replace(' BISTRA TILL ', ' BISTRA_TILL ')
    line = line.replace(' BITA AV ', ' BITA_AV ')
    line = line.replace(' BITA IFR@N SIG ', ' BITA_IFR@N_SIG ')
    line = line.replace(' BITA IHJ$L ', ' BITA_IHJ$L ')
    line = line.replace(' BITA IHOP ', ' BITA_IHOP ')
    line = line.replace(' BITA S#NDER ', ' BITA_S#NDER ')
    line = line.replace(' BITA SIG ', ' BITA_SIG ')
    line = line.replace(' BITA SIG FAST ', ' BITA_SIG_FAST ')
    line = line.replace(' BJ$BBA EMOT ', ' BJ$BBA_EMOT ')
    line = line.replace(' BJUDA #VER ', ' BJUDA_#VER ')
    line = line.replace(' BJUDA EMOT ', ' BJUDA_EMOT ')
    line = line.replace(' BJUDA HEM ', ' BJUDA_HEM ')
    line = line.replace(' BJUDA IN ', ' BJUDA_IN ')
    line = line.replace(' BJUDA OMKRING ', ' BJUDA_OMKRING ')
    line = line.replace(' BJUDA TILL ', ' BJUDA_TILL ')
    line = line.replace(' BJUDA UPP ', ' BJUDA_UPP ')
    line = line.replace(' BJUDA UT ', ' BJUDA_UT ')
    line = line.replace(' BL A ', ' BL_A ')
    line = line.replace(' BL@SA AV ', ' BL@SA_AV ')
    line = line.replace(' BL@SA BORT ', ' BL@SA_BORT ')
    line = line.replace(' BL@SA IN ', ' BL@SA_IN ')
    line = line.replace(' BL@SA NED ', ' BL@SA_NED ')
    line = line.replace(' BL@SA OMKULL ', ' BL@SA_OMKULL ')
    line = line.replace(' BL@SA UNDER ', ' BL@SA_UNDER ')
    line = line.replace(' BL@SA UPP ', ' BL@SA_UPP ')
    line = line.replace(' BL@SA UT ', ' BL@SA_UT ')
    line = line.replace(' BL#DA IGENOM ', ' BL#DA_IGENOM ')
    line = line.replace(' BL#DA NED ', ' BL#DA_NED ')
    line = line.replace(' BL#TA IGENOM ', ' BL#TA_IGENOM ')
    line = line.replace(' BL#TA NED ', ' BL#TA_NED ')
    line = line.replace(' BL#TA UPP ', ' BL#TA_UPP ')
    line = line.replace(' BL$CKA NED ', ' BL$CKA_NED ')
    line = line.replace(' BL$DDRA IGENOM ', ' BL$DDRA_IGENOM ')
    line = line.replace(' BL$NDA AV ', ' BL$NDA_AV ')
    line = line.replace(' BL$NDA NER ', ' BL$NDA_NER ')
    line = line.replace(' BL$NKA FRAM ', ' BL$NKA_FRAM ')
    line = line.replace(' BL$NKA TILL ', ' BL$NKA_TILL ')
    line = line.replace(' BLAMERA SIG ', ' BLAMERA_SIG ')
    line = line.replace(' BLANDA BORT ', ' BLANDA_BORT ')
    line = line.replace(' BLANDA I ', ' BLANDA_I ')
    line = line.replace(' BLANDA IHOP ', ' BLANDA_IHOP ')
    line = line.replace(' BLANDA IN ', ' BLANDA_IN ')
    line = line.replace(' BLANDA SAMMAN ', ' BLANDA_SAMMAN ')
    line = line.replace(' BLANDA SIG ', ' BLANDA_SIG ')
    line = line.replace(' BLANDA SIG I ', ' BLANDA_SIG_I ')
    line = line.replace(' BLANDA TILL ', ' BLANDA_TILL ')
    line = line.replace(' BLANDA UPP ', ' BLANDA_UPP ')
    line = line.replace(' BLANDA UT ', ' BLANDA_UT ')
    line = line.replace(' BLASTA AV ', ' BLASTA_AV ')
    line = line.replace(' BLI #VER ', ' BLI_#VER ')
    line = line.replace(' BLI AV ', ' BLI_AV ')
    line = line.replace(' BLI AV MED ', ' BLI_AV_MED ')
    line = line.replace(' BLI EFTER ', ' BLI_EFTER ')
    line = line.replace(' BLI KVAR ', ' BLI_KVAR ')
    line = line.replace(' BLI TILL ', ' BLI_TILL ')
    line = line.replace(' BLI UTAN ', ' BLI_UTAN ')
    line = line.replace(' BLICKA TILLBAKA ', ' BLICKA_TILLBAKA ')
    line = line.replace(' BLINKA TILL ', ' BLINKA_TILL ')
    line = line.replace(' BLIXTRA TILL ', ' BLIXTRA_TILL ')
    line = line.replace(' BLODA NED ', ' BLODA_NED ')
    line = line.replace(' BLOMMA #VER ', ' BLOMMA_#VER ')
    line = line.replace(' BLOMMA UT ', ' BLOMMA_UT ')
    line = line.replace(' BLOSSA UPP ', ' BLOSSA_UPP ')
    line = line.replace(' BLOTTA SIG ', ' BLOTTA_SIG ')
    line = line.replace(' BLUSA SIG ', ' BLUSA_SIG ')
    line = line.replace(' BO IN ', ' BO_IN ')
    line = line.replace(' BOCKA AV ', ' BOCKA_AV ')
    line = line.replace(' BOCKA F#R ', ' BOCKA_F#R ')
    line = line.replace(' BOCKA SIG ', ' BOCKA_SIG ')
    line = line.replace(' BOCKA TILL ', ' BOCKA_TILL ')
    line = line.replace(' BOKA IN ', ' BOKA_IN ')
    line = line.replace(' BOKA OM ', ' BOKA_OM ')
    line = line.replace(' BOMBA UT ', ' BOMBA_UT ')
    line = line.replace(' BOMMA F#R ', ' BOMMA_F#R ')
    line = line.replace(' BOMMA IGEN ', ' BOMMA_IGEN ')
    line = line.replace(' BOMMA TILL ', ' BOMMA_TILL ')
    line = line.replace(' BONA OM ', ' BONA_OM ')
    line = line.replace(' BORRA SIG IN ', ' BORRA_SIG_IN ')
    line = line.replace(' BORRA UPP ', ' BORRA_UPP ')
    line = line.replace(' BORSTA AV ', ' BORSTA_AV ')
    line = line.replace(' BORSTA BORT ', ' BORSTA_BORT ')
    line = line.replace(' BOXA TILL ', ' BOXA_TILL ')
    line = line.replace(' BR#STA AV ', ' BR#STA_AV ')
    line = line.replace(' BR#STA SIG ', ' BR#STA_SIG ')
    line = line.replace(' BR$NNA AV ', ' BR$NNA_AV ')
    line = line.replace(' BR$NNA BORT ', ' BR$NNA_BORT ')
    line = line.replace(' BR$NNA IGENOM ', ' BR$NNA_IGENOM ')
    line = line.replace(' BR$NNA NED ', ' BR$NNA_NED ')
    line = line.replace(' BR$NNA OPP ', ' BR$NNA_OPP ')
    line = line.replace(' BR$NNA SIG ', ' BR$NNA_SIG ')
    line = line.replace(' BR$NNA SIG IN ', ' BR$NNA_SIG_IN ')
    line = line.replace(' BR$NNA UPP ', ' BR$NNA_UPP ')
    line = line.replace(' BR$NNA VID ', ' BR$NNA_VID ')
    line = line.replace(' BRAKA IHOP ', ' BRAKA_IHOP ')
    line = line.replace(' BRAKA L#S ', ' BRAKA_L#S ')
    line = line.replace(' BRAKA SAMMAN ', ' BRAKA_SAMMAN ')
    line = line.replace(' BRAKA TILL ', ' BRAKA_TILL ')
    line = line.replace(' BRASSA P@ ', ' BRASSA_P@ ')
    line = line.replace(' BREDA P@ ', ' BREDA_P@ ')
    line = line.replace(' BREDA UT ', ' BREDA_UT ')
    line = line.replace(' BREDA UT SIG ', ' BREDA_UT_SIG ')
    line = line.replace(' BRINGA #VER ', ' BRINGA_#VER ')
    line = line.replace(' BRINGA NED ', ' BRINGA_NED ')
    line = line.replace(' BRINNA AV ', ' BRINNA_AV ')
    line = line.replace(' BRINNA NED ', ' BRINNA_NED ')
    line = line.replace(' BRINNA UPP ', ' BRINNA_UPP ')
    line = line.replace(' BRINNA UT ', ' BRINNA_UT ')
    line = line.replace(' BRISTA UT ', ' BRISTA_UT ')
    line = line.replace(' BRODERA UT ', ' BRODERA_UT ')
    line = line.replace(' BROMSA IN ', ' BROMSA_IN ')
    line = line.replace(' BROMSA UPP ', ' BROMSA_UPP ')
    line = line.replace(' BROTTA NER ', ' BROTTA_NER ')
    line = line.replace(' BRUSA UPP ', ' BRUSA_UPP ')
    line = line.replace(' BRY SIG ', ' BRY_SIG ')
    line = line.replace(' BRY SIG OM ', ' BRY_SIG_OM ')
    line = line.replace(' BRYGGA #VER ', ' BRYGGA_#VER ')
    line = line.replace(' BRYTA AV ', ' BRYTA_AV ')
    line = line.replace(' BRYTA FRAM ', ' BRYTA_FRAM ')
    line = line.replace(' BRYTA GENOM ', ' BRYTA_GENOM ')
    line = line.replace(' BRYTA I ', ' BRYTA_I ')
    line = line.replace(' BRYTA IGENOM ', ' BRYTA_IGENOM ')
    line = line.replace(' BRYTA IN ', ' BRYTA_IN ')
    line = line.replace(' BRYTA L#S ', ' BRYTA_L#S ')
    line = line.replace(' BRYTA LOSS ', ' BRYTA_LOSS ')
    line = line.replace(' BRYTA NED ', ' BRYTA_NED ')
    line = line.replace(' BRYTA OM ', ' BRYTA_OM ')
    line = line.replace(' BRYTA OPP ', ' BRYTA_OPP ')
    line = line.replace(' BRYTA SAMMAN ', ' BRYTA_SAMMAN ')
    line = line.replace(' BRYTA SIG ', ' BRYTA_SIG ')
    line = line.replace(' BRYTA SIG IN ', ' BRYTA_SIG_IN ')
    line = line.replace(' BRYTA SIG UT ', ' BRYTA_SIG_UT ')
    line = line.replace(' BRYTA UPP ', ' BRYTA_UPP ')
    line = line.replace(' BRYTA UT ', ' BRYTA_UT ')
    line = line.replace(' BUA UT ', ' BUA_UT ')
    line = line.replace(' BUBBLA #VER ', ' BUBBLA_#VER ')
    line = line.replace(' BUBBLA UPP ', ' BUBBLA_UPP ')
    line = line.replace(' BUCKLA IN ', ' BUCKLA_IN ')
    line = line.replace(' BUCKLA SIG ', ' BUCKLA_SIG ')
    line = line.replace(' BUCKLA TILL ', ' BUCKLA_TILL ')
    line = line.replace(' BUFFA TILL ', ' BUFFA_TILL ')
    line = line.replace(' BUFFRA UPP ', ' BUFFRA_UPP ')
    line = line.replace(' BUGA SIG ', ' BUGA_SIG ')
    line = line.replace(' BUKA UT ', ' BUKA_UT ')
    line = line.replace(' BUKTA SIG ', ' BUKTA_SIG ')
    line = line.replace(' BUKTA UT ', ' BUKTA_UT ')
    line = line.replace(' BULLA UPP ', ' BULLA_UPP ')
    line = line.replace(' BULTA IN ', ' BULTA_IN ')
    line = line.replace(' BULTA NED ', ' BULTA_NED ')
    line = line.replace(' BULTA TILL ', ' BULTA_TILL ')
    line = line.replace(' BULTA UT ', ' BULTA_UT ')
    line = line.replace(' BUNKRA UPP ', ' BUNKRA_UPP ')
    line = line.replace(' BUNTA IHOP ', ' BUNTA_IHOP ')
    line = line.replace(' BURA IN ', ' BURA_IN ')
    line = line.replace(' BURRA UPP ', ' BURRA_UPP ')
    line = line.replace(' BYGGA BORT ', ' BYGGA_BORT ')
    line = line.replace(' BYGGA IHOP ', ' BYGGA_IHOP ')
    line = line.replace(' BYGGA IN ', ' BYGGA_IN ')
    line = line.replace(' BYGGA OM ', ' BYGGA_OM ')
    line = line.replace(' BYGGA OPP ', ' BYGGA_OPP ')
    line = line.replace(' BYGGA TILL ', ' BYGGA_TILL ')
    line = line.replace(' BYGGA UPP ', ' BYGGA_UPP ')
    line = line.replace(' BYGGA UT ', ' BYGGA_UT ')
    line = line.replace(' BYLTA IHOP ', ' BYLTA_IHOP ')
    line = line.replace(' BYLTA IN ', ' BYLTA_IN ')
    line = line.replace(' BYLTA P@ ', ' BYLTA_P@ ')
    line = line.replace(' BYTA AV ', ' BYTA_AV ')
    line = line.replace(' BYTA BORT ', ' BYTA_BORT ')
    line = line.replace(' BYTA IN ', ' BYTA_IN ')
    line = line.replace(' BYTA OM ', ' BYTA_OM ')
    line = line.replace(' BYTA TILL SIG ', ' BYTA_TILL_SIG ')
    line = line.replace(' BYTA UPP SIG ', ' BYTA_UPP_SIG ')
    line = line.replace(' BYTA UT ', ' BYTA_UT ')
    line = line.replace(' CHARTRA IN ', ' CHARTRA_IN ')
    line = line.replace(' CHECKA AV ', ' CHECKA_AV ')
    line = line.replace(' CHECKA IN ', ' CHECKA_IN ')
    line = line.replace(' CHECKA UPP ', ' CHECKA_UPP ')
    line = line.replace(' CHECKA UT ', ' CHECKA_UT ')
    line = line.replace(' CHOSA SIG ', ' CHOSA_SIG ')
    line = line.replace(' COOLA NED ', ' COOLA_NED ')
    line = line.replace(' CREME FRAICHE ', ' CREME_FRAICHE ')
    line = line.replace(' D@SA BORT ', ' D@SA_BORT ')
    line = line.replace(' D# BORT ', ' D#_BORT ')
    line = line.replace(' D# UNDAN ', ' D#_UNDAN ')
    line = line.replace(' D# UT ', ' D#_UT ')
    line = line.replace(' D#LJA SIG ', ' D#LJA_SIG ')
    line = line.replace(' D#MA UT ', ' D#MA_UT ')
    line = line.replace(' D#PA OM ', ' D#PA_OM ')
    line = line.replace(' D$MMA AV ', ' D$MMA_AV ')
    line = line.replace(' D$MMA F#R ', ' D$MMA_F#R ')
    line = line.replace(' D$MMA IN ', ' D$MMA_IN ')
    line = line.replace(' D$MMA TILL ', ' D$MMA_TILL ')
    line = line.replace(' D$MMA UPP ', ' D$MMA_UPP ')
    line = line.replace(' D$MPA NED ', ' D$MPA_NED ')
    line = line.replace(' D$MPA NER ', ' D$MPA_NER ')
    line = line.replace(' D$NGA IGEN ', ' D$NGA_IGEN ')
    line = line.replace(' D$NGA TILL ', ' D$NGA_TILL ')
    line = line.replace(' DABBA SIG ', ' DABBA_SIG ')
    line = line.replace(' DAMMA AV ', ' DAMMA_AV ')
    line = line.replace(' DAMMA BORT ', ' DAMMA_BORT ')
    line = line.replace(' DAMMA IHOP ', ' DAMMA_IHOP ')
    line = line.replace(' DAMMA P@ ', ' DAMMA_P@ ')
    line = line.replace(' DAMMA TILL ', ' DAMMA_TILL ')
    line = line.replace(' DANA OM ', ' DANA_OM ')
    line = line.replace(' DANSA AV ', ' DANSA_AV ')
    line = line.replace(' DANSA BORT ', ' DANSA_BORT ')
    line = line.replace(' DANSA F#RBI ', ' DANSA_F#RBI ')
    line = line.replace(' DANSA FRAM ', ' DANSA_FRAM ')
    line = line.replace(' DANSA IN ', ' DANSA_IN ')
    line = line.replace(' DANSA OMKRING ', ' DANSA_OMKRING ')
    line = line.replace(' DANSA P@ ', ' DANSA_P@ ')
    line = line.replace(' DANSA RUNT ', ' DANSA_RUNT ')
    line = line.replace(' DANSA UT ', ' DANSA_UT ')
    line = line.replace(' DASKA TILL ', ' DASKA_TILL ')
    line = line.replace(' DE FACTO ', ' DE_FACTO ')
    line = line.replace(' DE GAULLE ', ' DE_GAULLE ')
    line = line.replace(' DE LUXE ', ' DE_LUXE ')
    line = line.replace(' DEFILERA F#RBI ', ' DEFILERA_F#RBI ')
    line = line.replace(' DEKA NED SIG ', ' DEKA_NED_SIG ')
    line = line.replace(' DEKA NER SIG ', ' DEKA_NER_SIG ')
    line = line.replace(' DELA AV ', ' DELA_AV ')
    line = line.replace(' DELA IN ', ' DELA_IN ')
    line = line.replace(' DELA MED SIG ', ' DELA_MED_SIG ')
    line = line.replace(' DELA SIG ', ' DELA_SIG ')
    line = line.replace(' DELA UPP ', ' DELA_UPP ')
    line = line.replace(' DELA UPP SIG ', ' DELA_UPP_SIG ')
    line = line.replace(' DELA UT ', ' DELA_UT ')
    line = line.replace(' DELIRIUM TREMENS ', ' DELIRIUM_TREMENS ')
    line = line.replace(' DEMASKERA SIG ', ' DEMASKERA_SIG ')
    line = line.replace(' DEN D$R ', ' DEN_D$R ')
    line = line.replace(' DEN H$R ', ' DEN_H$R ')
    line = line.replace(' DET VILL S$GA ', ' DET_VILL_S$GA ')
    line = line.replace(' DIFFERENTIERA SIG ', ' DIFFERENTIERA_SIG ')
    line = line.replace(' DIKA UT ', ' DIKA_UT ')
    line = line.replace(' DIMPA NED ', ' DIMPA_NED ')
    line = line.replace(' DISKA AV ', ' DISKA_AV ')
    line = line.replace(' DISKA UPP ', ' DISKA_UPP ')
    line = line.replace(' DITT OCH DATT ', ' DITT_OCH_DATT ')
    line = line.replace(' DOKUMENTERA SIG ', ' DOKUMENTERA_SIG ')
    line = line.replace(' DOMNA AV ', ' DOMNA_AV ')
    line = line.replace(' DOMNA BORT ', ' DOMNA_BORT ')
    line = line.replace(' DOPPA NER ', ' DOPPA_NER ')
    line = line.replace(' DOPPA SIG ', ' DOPPA_SIG ')
    line = line.replace(' DR@SA I ', ' DR@SA_I ')
    line = line.replace(' DR@SA NER ', ' DR@SA_NER ')
    line = line.replace(' DR@SA OMKULL ', ' DR@SA_OMKULL ')
    line = line.replace(' DR#MMA BORT ', ' DR#MMA_BORT ')
    line = line.replace(' DR#MMA SIG BORT ', ' DR#MMA_SIG_BORT ')
    line = line.replace(' DR#MMA SIG TILLBAKA ', ' DR#MMA_SIG_TILLBAKA ')
    line = line.replace(' DR#SA NED ', ' DR#SA_NED ')
    line = line.replace(' DR#SA NER ', ' DR#SA_NER ')
    line = line.replace(' DR$LLA OMKRING ', ' DR$LLA_OMKRING ')
    line = line.replace(' DR$MMA I MED ', ' DR$MMA_I_MED ')
    line = line.replace(' DR$MMA IGEN ', ' DR$MMA_IGEN ')
    line = line.replace(' DR$MMA TILL ', ' DR$MMA_TILL ')
    line = line.replace(' DR$NKA IN ', ' DR$NKA_IN ')
    line = line.replace(' DR$NKA SIG ', ' DR$NKA_SIG ')
    line = line.replace(' DRA @T ', ' DRA_@T ')
    line = line.replace(' DRA @T SIG ', ' DRA_@T_SIG ')
    line = line.replace(' DRA #VER ', ' DRA_#VER ')
    line = line.replace(' DRA AV ', ' DRA_AV ')
    line = line.replace(' DRA BORT ', ' DRA_BORT ')
    line = line.replace(' DRA F#R ', ' DRA_F#R ')
    line = line.replace(' DRA FRAM ', ' DRA_FRAM ')
    line = line.replace(' DRA IFR@N ', ' DRA_IFR@N ')
    line = line.replace(' DRA IG@NG ', ' DRA_IG@NG ')
    line = line.replace(' DRA IGEN ', ' DRA_IGEN ')
    line = line.replace(' DRA IGENOM ', ' DRA_IGENOM ')
    line = line.replace(' DRA IHOP ', ' DRA_IHOP ')
    line = line.replace(' DRA IHOP SIG ', ' DRA_IHOP_SIG ')
    line = line.replace(' DRA IN ', ' DRA_IN ')
    line = line.replace(' DRA IS$R ', ' DRA_IS$R ')
    line = line.replace(' DRA IV$G ', ' DRA_IV$G ')
    line = line.replace(' DRA J$MNT ', ' DRA_J$MNT ')
    line = line.replace(' DRA MED ', ' DRA_MED ')
    line = line.replace(' DRA MED SIG ', ' DRA_MED_SIG ')
    line = line.replace(' DRA NED ', ' DRA_NED ')
    line = line.replace(' DRA OMKRING ', ' DRA_OMKRING ')
    line = line.replace(' DRA OMKULL ', ' DRA_OMKULL ')
    line = line.replace(' DRA P@ ', ' DRA_P@ ')
    line = line.replace(' DRA P@ SIG ', ' DRA_P@_SIG ')
    line = line.replace(' DRA SAMMAN ', ' DRA_SAMMAN ')
    line = line.replace(' DRA SIG ', ' DRA_SIG ')
    line = line.replace(' DRA SIG BORT ', ' DRA_SIG_BORT ')
    line = line.replace(' DRA SIG FRAM ', ' DRA_SIG_FRAM ')
    line = line.replace(' DRA SIG TILLBAKA ', ' DRA_SIG_TILLBAKA ')
    line = line.replace(' DRA TILL ', ' DRA_TILL ')
    line = line.replace(' DRA TILL SIG ', ' DRA_TILL_SIG ')
    line = line.replace(' DRA TILLBAKA ', ' DRA_TILLBAKA ')
    line = line.replace(' DRA UNDAN ', ' DRA_UNDAN ')
    line = line.replace(' DRA UPP ', ' DRA_UPP ')
    line = line.replace(' DRA UR ', ' DRA_UR ')
    line = line.replace(' DRA UT ', ' DRA_UT ')
    line = line.replace(' DRABBA IHOP ', ' DRABBA_IHOP ')
    line = line.replace(' DRABBA SAMMAN ', ' DRABBA_SAMMAN ')
    line = line.replace(' DRAPERA SIG ', ' DRAPERA_SIG ')
    line = line.replace(' DRAS MED ', ' DRAS_MED ')
    line = line.replace(' DRATTA OMKULL ', ' DRATTA_OMKULL ')
    line = line.replace(' DREGLA NED ', ' DREGLA_NED ')
    line = line.replace(' DREGLA NER ', ' DREGLA_NER ')
    line = line.replace(' DREJA BI ', ' DREJA_BI ')
    line = line.replace(' DRIBBLA AV ', ' DRIBBLA_AV ')
    line = line.replace(' DRIBBLA BORT ', ' DRIBBLA_BORT ')
    line = line.replace(' DRICKA UPP ', ' DRICKA_UPP ')
    line = line.replace(' DRICKA UR ', ' DRICKA_UR ')
    line = line.replace(' DRISTA SIG ', ' DRISTA_SIG ')
    line = line.replace(' DRIVA BORT ', ' DRIVA_BORT ')
    line = line.replace(' DRIVA FRAM ', ' DRIVA_FRAM ')
    line = line.replace(' DRIVA I ', ' DRIVA_I ')
    line = line.replace(' DRIVA IGENOM ', ' DRIVA_IGENOM ')
    line = line.replace(' DRIVA IN ', ' DRIVA_IN ')
    line = line.replace(' DRIVA IS$R ', ' DRIVA_IS$R ')
    line = line.replace(' DRIVA NED ', ' DRIVA_NED ')
    line = line.replace(' DRIVA NER ', ' DRIVA_NER ')
    line = line.replace(' DRIVA OMKRING ', ' DRIVA_OMKRING ')
    line = line.replace(' DRIVA P@ ', ' DRIVA_P@ ')
    line = line.replace(' DRIVA TILLBAKA ', ' DRIVA_TILLBAKA ')
    line = line.replace(' DRIVA UNDAN ', ' DRIVA_UNDAN ')
    line = line.replace(' DRIVA UT ', ' DRIVA_UT ')
    line = line.replace(' DRIVE IN ', ' DRIVE_IN ')
    line = line.replace(' DROP IN ', ' DROP_IN ')
    line = line.replace(' DROPPA AV ', ' DROPPA_AV ')
    line = line.replace(' DROPPA I ', ' DROPPA_I ')
    line = line.replace(' DROPPA NER ', ' DROPPA_NER ')
    line = line.replace(' DRULLA I ', ' DRULLA_I ')
    line = line.replace(' DRULLA OMKULL ', ' DRULLA_OMKULL ')
    line = line.replace(' DRUMLA I ', ' DRUMLA_I ')
    line = line.replace(' DRUMLA OMKULL ', ' DRUMLA_OMKULL ')
    line = line.replace(' DRYGA UT ', ' DRYGA_UT ')
    line = line.replace(' DRYPA AV ', ' DRYPA_AV ')
    line = line.replace(' DRYPA I ', ' DRYPA_I ')
    line = line.replace(' DRYPA NED ', ' DRYPA_NED ')
    line = line.replace(' DUGA TILL ', ' DUGA_TILL ')
    line = line.replace(' DUKA AV ', ' DUKA_AV ')
    line = line.replace(' DUKA FRAM ', ' DUKA_FRAM ')
    line = line.replace(' DUKA UNDER ', ' DUKA_UNDER ')
    line = line.replace(' DUKA UPP ', ' DUKA_UPP ')
    line = line.replace(' DUMMA SIG ', ' DUMMA_SIG ')
    line = line.replace(' DUNA NED ', ' DUNA_NED ')
    line = line.replace(' DUNDRA FRAM ', ' DUNDRA_FRAM ')
    line = line.replace(' DUNDRA TILL ', ' DUNDRA_TILL ')
    line = line.replace(' DUNKA I ', ' DUNKA_I ')
    line = line.replace(' DUNKA TILL ', ' DUNKA_TILL ')
    line = line.replace(' DUNSA I ', ' DUNSA_I ')
    line = line.replace(' DUNSA MOT ', ' DUNSA_MOT ')
    line = line.replace(' DUNSTA AV ', ' DUNSTA_AV ')
    line = line.replace(' DUNSTA BORT ', ' DUNSTA_BORT ')
    line = line.replace(' DUTTA TILL ', ' DUTTA_TILL ')
    line = line.replace(' DYKA NED ', ' DYKA_NED ')
    line = line.replace(' DYKA NER ', ' DYKA_NER ')
    line = line.replace(' DYKA UPP ', ' DYKA_UPP ')
    line = line.replace(' DYRKA UPP ', ' DYRKA_UPP ')
    line = line.replace(' DYSTRA TILL ', ' DYSTRA_TILL ')
    line = line.replace(' DYVLA P@ ', ' DYVLA_P@ ')
    line = line.replace(' EBBA UT ', ' EBBA_UT ')
    line = line.replace(' EFTERR$TTA SIG ', ' EFTERR$TTA_SIG ')
    line = line.replace(' EGGA UPP ', ' EGGA_UPP ')
    line = line.replace(' ELDA UPP ', ' ELDA_UPP ')
    line = line.replace(' EN CARRE ', ' EN_CARRE ')
    line = line.replace(' EN FACE ', ' EN_FACE ')
    line = line.replace(' EN GROS ', ' EN_GROS ')
    line = line.replace(' EN MASS ', ' EN_MASS ')
    line = line.replace(' EN MASSE ', ' EN_MASSE ')
    line = line.replace(' EXPEKTORERA SIG ', ' EXPEKTORERA_SIG ')
    line = line.replace(' F@ BORT ', ' F@_BORT ')
    line = line.replace(' F@ F#R SIG ', ' F@_F#R_SIG ')
    line = line.replace(' F@ FRAM ', ' F@_FRAM ')
    line = line.replace(' F@ I SIG ', ' F@_I_SIG ')
    line = line.replace(' F@ IN ', ' F@_IN ')
    line = line.replace(' F@ LOSS ', ' F@_LOSS ')
    line = line.replace(' F@ MED SIG ', ' F@_MED_SIG ')
    line = line.replace(' F@ UPP ', ' F@_UPP ')
    line = line.replace(' F@ UR SIG ', ' F@_UR_SIG ')
    line = line.replace(' F@ UT ', ' F@_UT ')
    line = line.replace(' F@NA SIG ', ' F@NA_SIG ')
    line = line.replace(' F#DA UPP ', ' F#DA_UPP ')
    line = line.replace(' F#LJA MED ', ' F#LJA_MED ')
    line = line.replace(' F#LJA UPP ', ' F#LJA_UPP ')
    line = line.replace(' F#R LIVET ', ' F#R_LIVET ')
    line = line.replace(' F#R N@T ', ' F#R_N@T ')
    line = line.replace(' F#R#KA SIG ', ' F#R#KA_SIG ')
    line = line.replace(' F#R$LSKA SIG ', ' F#R$LSKA_SIG ')
    line = line.replace(' F#R$NDRA SIG ', ' F#R$NDRA_SIG ')
    line = line.replace(' F#RA #VER ', ' F#RA_#VER ')
    line = line.replace(' F#RA BORT ', ' F#RA_BORT ')
    line = line.replace(' F#RA FRAM ', ' F#RA_FRAM ')
    line = line.replace(' F#RA IHOP ', ' F#RA_IHOP ')
    line = line.replace(' F#RA IN ', ' F#RA_IN ')
    line = line.replace(' F#RA MED SIG ', ' F#RA_MED_SIG ')
    line = line.replace(' F#RA UPP ', ' F#RA_UPP ')
    line = line.replace(' F#RA UT ', ' F#RA_UT ')
    line = line.replace(' F#RB$TTRA SIG ', ' F#RB$TTRA_SIG ')
    line = line.replace(' F#RBARMA SIG ', ' F#RBARMA_SIG ')
    line = line.replace(' F#RBEREDA SIG ', ' F#RBEREDA_SIG ')
    line = line.replace(' F#RDELA SIG ', ' F#RDELA_SIG ')
    line = line.replace(' F#RDJUPA SIG ', ' F#RDJUPA_SIG ')
    line = line.replace(' F#RE DETTA ', ' F#RE_DETTA ')
    line = line.replace(' F#RENA SIG ', ' F#RENA_SIG ')
    line = line.replace(' F#RES$TTA SIG ', ' F#RES$TTA_SIG ')
    line = line.replace(' F#RFLYTTA SIG ', ' F#RFLYTTA_SIG ')
    line = line.replace(' F#RFRISKA SIG ', ' F#RFRISKA_SIG ')
    line = line.replace(' F#RH@LLA SIG ', ' F#RH@LLA_SIG ')
    line = line.replace(' F#RH$RDA SIG ', ' F#RH$RDA_SIG ')
    line = line.replace(' F#RH$VA SIG ', ' F#RH$VA_SIG ')
    line = line.replace(' F#RHASTA SIG ', ' F#RHASTA_SIG ')
    line = line.replace(' F#RIRRA SIG ', ' F#RIRRA_SIG ')
    line = line.replace(' F#RIVRA SIG ', ' F#RIVRA_SIG ')
    line = line.replace(' F#RKLARA BORT ', ' F#RKLARA_BORT ')
    line = line.replace(' F#RKLARA SIG ', ' F#RKLARA_SIG ')
    line = line.replace(' F#RKOVRA SIG ', ' F#RKOVRA_SIG ')
    line = line.replace(' F#RLIKA SIG ', ' F#RLIKA_SIG ')
    line = line.replace(' F#RLITA SIG ', ' F#RLITA_SIG ')
    line = line.replace(' F#RLORA SIG ', ' F#RLORA_SIG ')
    line = line.replace(' F#RLOVA SIG ', ' F#RLOVA_SIG ')
    line = line.replace(' F#RLUSTA SIG ', ' F#RLUSTA_SIG ')
    line = line.replace(' F#RLYFTA SIG ', ' F#RLYFTA_SIG ')
    line = line.replace(' F#RM@ SIG ', ' F#RM@_SIG ')
    line = line.replace(' F#RNEDRA SIG ', ' F#RNEDRA_SIG ')
    line = line.replace(' F#RNEKA SIG ', ' F#RNEKA_SIG ')
    line = line.replace(' F#RS#RJA SIG ', ' F#RS#RJA_SIG ')
    line = line.replace(' F#RS$GA SIG ', ' F#RS$GA_SIG ')
    line = line.replace(' F#RS$KRA SIG ', ' F#RS$KRA_SIG ')
    line = line.replace(' F#RS$TTA SIG ', ' F#RS$TTA_SIG ')
    line = line.replace(' F#RSAMLA SIG ', ' F#RSAMLA_SIG ')
    line = line.replace(' F#RSE SIG ', ' F#RSE_SIG ')
    line = line.replace(' F#RSKRIVA SIG ', ' F#RSKRIVA_SIG ')
    line = line.replace(' F#RSOVA SIG ', ' F#RSOVA_SIG ')
    line = line.replace(' F#RSVARA SIG ', ' F#RSVARA_SIG ')
    line = line.replace(' F#RV$NTA SIG ', ' F#RV$NTA_SIG ')
    line = line.replace(' F#RVILLA SIG ', ' F#RVILLA_SIG ')
    line = line.replace(' F#RVISSA SIG ', ' F#RVISSA_SIG ')
    line = line.replace(' F$LLA IN ', ' F$LLA_IN ')
    line = line.replace(' F$LLA NER ', ' F$LLA_NER ')
    line = line.replace(' F$LLA UPP ', ' F$LLA_UPP ')
    line = line.replace(' F$LLA UT ', ' F$LLA_UT ')
    line = line.replace(' F$RGA AV SIG ', ' F$RGA_AV_SIG ')
    line = line.replace(' F$STA SIG ', ' F$STA_SIG ')
    line = line.replace(' F$STA UPP ', ' F$STA_UPP ')
    line = line.replace(' FABLA IHOP ', ' FABLA_IHOP ')
    line = line.replace(' FAIT ACCOMPLI ', ' FAIT_ACCOMPLI ')
    line = line.replace(' FALLA AV ', ' FALLA_AV ')
    line = line.replace(' FALLA BORT ', ' FALLA_BORT ')
    line = line.replace(' FALLA IFR@N ', ' FALLA_IFR@N ')
    line = line.replace(' FALLA IGENOM ', ' FALLA_IGENOM ')
    line = line.replace(' FALLA IHOP ', ' FALLA_IHOP ')
    line = line.replace(' FALLA IN ', ' FALLA_IN ')
    line = line.replace(' FALLA IS$R ', ' FALLA_IS$R ')
    line = line.replace(' FALLA NED ', ' FALLA_NED ')
    line = line.replace(' FALLA S#NDER ', ' FALLA_S#NDER ')
    line = line.replace(' FALLA SIG ', ' FALLA_SIG ')
    line = line.replace(' FALLA TILLBAKA ', ' FALLA_TILLBAKA ')
    line = line.replace(' FALLA UNDAN ', ' FALLA_UNDAN ')
    line = line.replace(' FALLA UT ', ' FALLA_UT ')
    line = line.replace(' FARA #VER ', ' FARA_#VER ')
    line = line.replace(' FARA F#RBI ', ' FARA_F#RBI ')
    line = line.replace(' FARA FRAM ', ' FARA_FRAM ')
    line = line.replace(' FARA I ', ' FARA_I ')
    line = line.replace(' FARA I MIG ', ' FARA_I_MIG ')
    line = line.replace(' FARA IFR@N ', ' FARA_IFR@N ')
    line = line.replace(' FARA IN ', ' FARA_IN ')
    line = line.replace(' FARA P@ ', ' FARA_P@ ')
    line = line.replace(' FARA UPP ', ' FARA_UPP ')
    line = line.replace(' FARA UT ', ' FARA_UT ')
    line = line.replace(' FASA IN ', ' FASA_IN ')
    line = line.replace(' FASA UT ', ' FASA_UT ')
    line = line.replace(' FATTA POSTO ', ' FATTA_POSTO ')
    line = line.replace(' FATTA SIG KORT ', ' FATTA_SIG_KORT ')
    line = line.replace(' FATTA TAG ', ' FATTA_TAG ')
    line = line.replace(' FESTA UPP ', ' FESTA_UPP ')
    line = line.replace(' FETNA TILL ', ' FETNA_TILL ')
    line = line.replace(' FETTA IN ', ' FETTA_IN ')
    line = line.replace(' FIFFA UPP ', ' FIFFA_UPP ')
    line = line.replace(' FILA AV ', ' FILA_AV ')
    line = line.replace(' FILA BORT ', ' FILA_BORT ')
    line = line.replace(' FILTA SIG ', ' FILTA_SIG ')
    line = line.replace(' FINNA P@ ', ' FINNA_P@ ')
    line = line.replace(' FINNA SIG ', ' FINNA_SIG ')
    line = line.replace(' FINNA SIG I ', ' FINNA_SIG_I ')
    line = line.replace(' FINNAS KVAR ', ' FINNAS_KVAR ')
    line = line.replace(' FINNAS TILL ', ' FINNAS_TILL ')
    line = line.replace(' FIRA NED ', ' FIRA_NED ')
    line = line.replace(' FISKA UPP ', ' FISKA_UPP ')
    line = line.replace(' FIXA TILL ', ' FIXA_TILL ')
    line = line.replace(' FJ$LLA SIG ', ' FJ$LLA_SIG ')
    line = line.replace(' FJ$RMA SIG ', ' FJ$RMA_SIG ')
    line = line.replace(' FJOMPA SIG ', ' FJOMPA_SIG ')
    line = line.replace(' FL#DA #VER ', ' FL#DA_#VER ')
    line = line.replace(' FL#DA UT ', ' FL#DA_UT ')
    line = line.replace(' FL$CKA NER ', ' FL$CKA_NER ')
    line = line.replace(' FL$KA SIG ', ' FL$KA_SIG ')
    line = line.replace(' FL$KA UPP ', ' FL$KA_UPP ')
    line = line.replace(' FL$TA IHOP ', ' FL$TA_IHOP ')
    line = line.replace(' FL$TA IN ', ' FL$TA_IN ')
    line = line.replace(' FL$TA IN SIG ', ' FL$TA_IN_SIG ')
    line = line.replace(' FLAGA AV ', ' FLAGA_AV ')
    line = line.replace(' FLAGA SIG ', ' FLAGA_SIG ')
    line = line.replace(' FLAGNA AV ', ' FLAGNA_AV ')
    line = line.replace(' FLAMMA UPP ', ' FLAMMA_UPP ')
    line = line.replace(' FLICKA IN ', ' FLICKA_IN ')
    line = line.replace(' FLIKA IN ', ' FLIKA_IN ')
    line = line.replace(' FLIPPRA UT ', ' FLIPPRA_UT ')
    line = line.replace(' FLISA SIG ', ' FLISA_SIG ')
    line = line.replace(' FLOCKA SIG ', ' FLOCKA_SIG ')
    line = line.replace(' FLOTTA NER ', ' FLOTTA_NER ')
    line = line.replace(' FLYGA #VER ', ' FLYGA_#VER ')
    line = line.replace(' FLYGA BORT ', ' FLYGA_BORT ')
    line = line.replace(' FLYGA F#RBI ', ' FLYGA_F#RBI ')
    line = line.replace(' FLYGA I MIG ', ' FLYGA_I_MIG ')
    line = line.replace(' FLYGA IN ', ' FLYGA_IN ')
    line = line.replace(' FLYGA P@ ', ' FLYGA_P@ ')
    line = line.replace(' FLYGA UPP ', ' FLYGA_UPP ')
    line = line.replace(' FLYGA UT ', ' FLYGA_UT ')
    line = line.replace(' FLYTA KRING ', ' FLYTA_KRING ')
    line = line.replace(' FLYTA SAMMAN ', ' FLYTA_SAMMAN ')
    line = line.replace(' FLYTA UPP ', ' FLYTA_UPP ')
    line = line.replace(' FLYTA UT ', ' FLYTA_UT ')
    line = line.replace(' FLYTTA BORT ', ' FLYTTA_BORT ')
    line = line.replace(' FLYTTA FRAM ', ' FLYTTA_FRAM ')
    line = line.replace(' FLYTTA IN ', ' FLYTTA_IN ')
    line = line.replace(' FLYTTA OM ', ' FLYTTA_OM ')
    line = line.replace(' FLYTTA SIG ', ' FLYTTA_SIG ')
    line = line.replace(' FLYTTA UT ', ' FLYTTA_UT ')
    line = line.replace(' FOGA IHOP ', ' FOGA_IHOP ')
    line = line.replace(' FOGA IN ', ' FOGA_IN ')
    line = line.replace(' FOGA SIG ', ' FOGA_SIG ')
    line = line.replace(' FOLKA SIG ', ' FOLKA_SIG ')
    line = line.replace(' FORCE MAJEURE ', ' FORCE_MAJEURE ')
    line = line.replace(' FORMA OM ', ' FORMA_OM ')
    line = line.replace(' FORMA SIG ', ' FORMA_SIG ')
    line = line.replace(' FORSLA BORT ', ' FORSLA_BORT ')
    line = line.replace(' FORTA SIG ', ' FORTA_SIG ')
    line = line.replace(' FR@GA OM ', ' FR@GA_OM ')
    line = line.replace(' FR@GA SIG ', ' FR@GA_SIG ')
    line = line.replace(' FR@GA UT ', ' FR@GA_UT ')
    line = line.replace(' FR@NS$GA SIG ', ' FR@NS$GA_SIG ')
    line = line.replace(' FR@NSV$RA SIG ', ' FR@NSV$RA_SIG ')
    line = line.replace(' FR#JDA SIG ', ' FR#JDA_SIG ')
    line = line.replace(' FR$SA AV ', ' FR$SA_AV ')
    line = line.replace(' FR$SA P@ ', ' FR$SA_P@ ')
    line = line.replace(' FR$SA TILL ', ' FR$SA_TILL ')
    line = line.replace(' FR$SA UPP ', ' FR$SA_UPP ')
    line = line.replace(' FR$SA UR ', ' FR$SA_UR ')
    line = line.replace(' FR$SCHA UPP ', ' FR$SCHA_UPP ')
    line = line.replace(' FR$TA BORT ', ' FR$TA_BORT ')
    line = line.replace(' FR$TA SIG IN ', ' FR$TA_SIG_IN ')
    line = line.replace(' FR$TA UPP ', ' FR$TA_UPP ')
    line = line.replace(' FRADGA SIG ', ' FRADGA_SIG ')
    line = line.replace(' FRAKTA BORT ', ' FRAKTA_BORT ')
    line = line.replace(' FRANSA SIG ', ' FRANSA_SIG ')
    line = line.replace(' FREDA SIG ', ' FREDA_SIG ')
    line = line.replace(' FRESTA P@ ', ' FRESTA_P@ ')
    line = line.replace(' FRIG#RA SIG ', ' FRIG#RA_SIG ')
    line = line.replace(' FRISKA I ', ' FRISKA_I ')
    line = line.replace(' FRISKNA TILL ', ' FRISKNA_TILL ')
    line = line.replace(' FROSTA AV ', ' FROSTA_AV ')
    line = line.replace(' FROSTA UR ', ' FROSTA_UR ')
    line = line.replace(' FROTTERA SIG ', ' FROTTERA_SIG ')
    line = line.replace(' FRYSA BORT ', ' FRYSA_BORT ')
    line = line.replace(' FRYSA FAST ', ' FRYSA_FAST ')
    line = line.replace(' FRYSA IGEN ', ' FRYSA_IGEN ')
    line = line.replace(' FRYSA IN ', ' FRYSA_IN ')
    line = line.replace(' FRYSA INNE ', ' FRYSA_INNE ')
    line = line.replace(' FRYSA P@ ', ' FRYSA_P@ ')
    line = line.replace(' FRYSA TILL ', ' FRYSA_TILL ')
    line = line.replace(' FRYSA UT ', ' FRYSA_UT ')
    line = line.replace(' FUNDERA UT ', ' FUNDERA_UT ')
    line = line.replace(' FUTTA P@ ', ' FUTTA_P@ ')
    line = line.replace(' FYLLA I ', ' FYLLA_I ')
    line = line.replace(' FYLLA P@ ', ' FYLLA_P@ ')
    line = line.replace(' FYLLA UPP ', ' FYLLA_UPP ')
    line = line.replace(' FYRA AV ', ' FYRA_AV ')
    line = line.replace(' G@ ANN ', ' G@_ANN ')
    line = line.replace(' G@ AV ', ' G@_AV ')
    line = line.replace(' G@ BORT ', ' G@_BORT ')
    line = line.replace(' G@ FRAM ', ' G@_FRAM ')
    line = line.replace(' G@ IN ', ' G@_IN ')
    line = line.replace(' G@ P@ ', ' G@_P@ ')
    line = line.replace(' G@ UPP ', ' G@_UPP ')
    line = line.replace(' G@ UT ', ' G@_UT ')
    line = line.replace(' G#DA SIG ', ' G#DA_SIG ')
    line = line.replace(' G#MMA SIG ', ' G#MMA_SIG ')
    line = line.replace(' G#MMA UNDAN ', ' G#MMA_UNDAN ')
    line = line.replace(' G#RA AV MED ', ' G#RA_AV_MED ')
    line = line.replace(' G#RA BORT SIG ', ' G#RA_BORT_SIG ')
    line = line.replace(' G#RA FAST ', ' G#RA_FAST ')
    line = line.replace(' G#RA SIG TILL ', ' G#RA_SIG_TILL ')
    line = line.replace(' G#RA UNDAN ', ' G#RA_UNDAN ')
    line = line.replace(' G#RA UPP ', ' G#RA_UPP ')
    line = line.replace(' GADDA IHOP SIG ', ' GADDA_IHOP_SIG ')
    line = line.replace(' GADDA SIG SAMMAN ', ' GADDA_SIG_SAMMAN ')
    line = line.replace(' GAFFLA EMOT ', ' GAFFLA_EMOT ')
    line = line.replace(' GALLRA UT ', ' GALLRA_UT ')
    line = line.replace(' GARDERA SIG ', ' GARDERA_SIG ')
    line = line.replace(' GASKA UPP ', ' GASKA_UPP ')
    line = line.replace(' GE AKT ', ' GE_AKT ')
    line = line.replace(' GE SIG ', ' GE_SIG ')
    line = line.replace(' GE UPP ', ' GE_UPP ')
    line = line.replace(' GE UT ', ' GE_UT ')
    line = line.replace(' GENERA SIG ', ' GENERA_SIG ')
    line = line.replace(' GIFTA BORT ', ' GIFTA_BORT ')
    line = line.replace(' GIFTA SIG ', ' GIFTA_SIG ')
    line = line.replace(' GIVA SIG AV ', ' GIVA_SIG_AV ')
    line = line.replace(' GJUTA AV ', ' GJUTA_AV ')
    line = line.replace(' GL#MMA AV ', ' GL#MMA_AV ')
    line = line.replace(' GL#MMA BORT ', ' GL#MMA_BORT ')
    line = line.replace(' GL#MMA KVAR ', ' GL#MMA_KVAR ')
    line = line.replace(' GL$DJA SIG ', ' GL$DJA_SIG ')
    line = line.replace(' GL$TTA UT ', ' GL$TTA_UT ')
    line = line.replace(' GLASA IN ', ' GLASA_IN ')
    line = line.replace(' GLESA UT ', ' GLESA_UT ')
    line = line.replace(' GLESNA UT ', ' GLESNA_UT ')
    line = line.replace(' GLIDA AV ', ' GLIDA_AV ')
    line = line.replace(' GLIMTA TILL ', ' GLIMTA_TILL ')
    line = line.replace(' GLUFSA I SIG ', ' GLUFSA_I_SIG ')
    line = line.replace(' GNAGA AV ', ' GNAGA_AV ')
    line = line.replace(' GNAGA BORT ', ' GNAGA_BORT ')
    line = line.replace(' GNIDA IN ', ' GNIDA_IN ')
    line = line.replace(' GONA SIG ', ' GONA_SIG ')
    line = line.replace(' GOTTA SIG ', ' GOTTA_SIG ')
    line = line.replace(' GR@TA UT ', ' GR@TA_UT ')
    line = line.replace(' GR#PA UR ', ' GR#PA_UR ')
    line = line.replace(' GR$DDA SIG ', ' GR$DDA_SIG ')
    line = line.replace(' GR$MA SIG ', ' GR$MA_SIG ')
    line = line.replace(' GR$VA NER ', ' GR$VA_NER ')
    line = line.replace(' GR$VA UPP ', ' GR$VA_UPP ')
    line = line.replace(' GRABBA @T SIG ', ' GRABBA_@T_SIG ')
    line = line.replace(' GRABBA TAG ', ' GRABBA_TAG ')
    line = line.replace(' GRENA SIG ', ' GRENA_SIG ')
    line = line.replace(' GREPPA TAG ', ' GREPPA_TAG ')
    line = line.replace(' GRIPA IN ', ' GRIPA_IN ')
    line = line.replace(' GRIPA TAG ', ' GRIPA_TAG ')
    line = line.replace(' GRISA NER ', ' GRISA_NER ')
    line = line.replace(' GRUNDA IGEN ', ' GRUNDA_IGEN ')
    line = line.replace(' GRUPPERA SIG ', ' GRUPPERA_SIG ')
    line = line.replace(' GRUVA SIG ', ' GRUVA_SIG ')
    line = line.replace(' GUBBA TILL SIG ', ' GUBBA_TILL_SIG ')
    line = line.replace(' GUMMA UPP ', ' GUMMA_UPP ')
    line = line.replace(' GURGLA SIG ', ' GURGLA_SIG ')
    line = line.replace(' GYTTRA IHOP SIG ', ' GYTTRA_IHOP_SIG ')
    line = line.replace(' GYTTRA SIG ', ' GYTTRA_SIG ')
    line = line.replace(' H@LLA AV ', ' H@LLA_AV ')
    line = line.replace(' H@LLA EFTER ', ' H@LLA_EFTER ')
    line = line.replace(' H@LLA EMOT ', ' H@LLA_EMOT ')
    line = line.replace(' H@LLA F#R ', ' H@LLA_F#R ')
    line = line.replace(' H@LLA FAST ', ' H@LLA_FAST ')
    line = line.replace(' H@LLA FRAM ', ' H@LLA_FRAM ')
    line = line.replace(' H@LLA I ', ' H@LLA_I ')
    line = line.replace(' H@LLA I SIG ', ' H@LLA_I_SIG ')
    line = line.replace(' H@LLA IG@NG ', ' H@LLA_IG@NG ')
    line = line.replace(' H@LLA IGEN ', ' H@LLA_IGEN ')
    line = line.replace(' H@LLA IHOP ', ' H@LLA_IHOP ')
    line = line.replace(' H@LLA INNE ', ' H@LLA_INNE ')
    line = line.replace(' H@LLA IS$R ', ' H@LLA_IS$R ')
    line = line.replace(' H@LLA KVAR ', ' H@LLA_KVAR ')
    line = line.replace(' H@LLA MED ', ' H@LLA_MED ')
    line = line.replace(' H@LLA NERE ', ' H@LLA_NERE ')
    line = line.replace(' H@LLA OM ', ' H@LLA_OM ')
    line = line.replace(' H@LLA P@ ', ' H@LLA_P@ ')
    line = line.replace(' H@LLA P@ MED ', ' H@LLA_P@_MED ')
    line = line.replace(' H@LLA SAMMAN ', ' H@LLA_SAMMAN ')
    line = line.replace(' H@LLA SIG ', ' H@LLA_SIG ')
    line = line.replace(' H@LLA SIG BORTA ', ' H@LLA_SIG_BORTA ')
    line = line.replace(' H@LLA SIG FRAMME ', ' H@LLA_SIG_FRAMME ')
    line = line.replace(' H@LLA SIG UNDAN ', ' H@LLA_SIG_UNDAN ')
    line = line.replace(' H@LLA SIG UPPE ', ' H@LLA_SIG_UPPE ')
    line = line.replace(' H@LLA TILL ', ' H@LLA_TILL ')
    line = line.replace(' H@LLA UNDAN ', ' H@LLA_UNDAN ')
    line = line.replace(' H@LLA UPP ', ' H@LLA_UPP ')
    line = line.replace(' H@LLA UPPE ', ' H@LLA_UPPE ')
    line = line.replace(' H@LLA UT ', ' H@LLA_UT ')
    line = line.replace(' H@RA NER ', ' H@RA_NER ')
    line = line.replace(' H#FTA TILL ', ' H#FTA_TILL ')
    line = line.replace(' H#JA SIG ', ' H#JA_SIG ')
    line = line.replace(' H#JA UPP ', ' H#JA_UPP ')
    line = line.replace(' H#RA AV ', ' H#RA_AV ')
    line = line.replace(' H#RA SIG F#R ', ' H#RA_SIG_F#R ')
    line = line.replace(' H#RA TILL ', ' H#RA_TILL ')
    line = line.replace(' H#RA UPP ', ' H#RA_UPP ')
    line = line.replace(' H#STA IN ', ' H#STA_IN ')
    line = line.replace(' H$FTA FAST ', ' H$FTA_FAST ')
    line = line.replace(' H$FTA IHOP ', ' H$FTA_IHOP ')
    line = line.replace(' H$KTA AV ', ' H$KTA_AV ')
    line = line.replace(' H$KTA FAST ', ' H$KTA_FAST ')
    line = line.replace(' H$KTA IGEN ', ' H$KTA_IGEN ')
    line = line.replace(' H$KTA IHOP ', ' H$KTA_IHOP ')
    line = line.replace(' H$KTA UPP ', ' H$KTA_UPP ')
    line = line.replace(' H$LLA #VER ', ' H$LLA_#VER ')
    line = line.replace(' H$LLA AV ', ' H$LLA_AV ')
    line = line.replace(' H$LLA BORT ', ' H$LLA_BORT ')
    line = line.replace(' H$LLA I ', ' H$LLA_I ')
    line = line.replace(' H$LLA P@ ', ' H$LLA_P@ ')
    line = line.replace(' H$LLA UPP ', ' H$LLA_UPP ')
    line = line.replace(' H$LLA UR ', ' H$LLA_UR ')
    line = line.replace(' H$LLA UT ', ' H$LLA_UT ')
    line = line.replace(' H$LSA P@ ', ' H$LSA_P@ ')
    line = line.replace(' H$MTA IN ', ' H$MTA_IN ')
    line = line.replace(' H$MTA SIG ', ' H$MTA_SIG ')
    line = line.replace(' H$MTA UT ', ' H$MTA_UT ')
    line = line.replace(' H$NDA SIG ', ' H$NDA_SIG ')
    line = line.replace(' H$NF#RA SIG ', ' H$NF#RA_SIG ')
    line = line.replace(' H$NGA AV ', ' H$NGA_AV ')
    line = line.replace(' H$NGA AV SIG ', ' H$NGA_AV_SIG ')
    line = line.replace(' H$NGA EFTER ', ' H$NGA_EFTER ')
    line = line.replace(' H$NGA F#R ', ' H$NGA_F#R ')
    line = line.replace(' H$NGA I ', ' H$NGA_I ')
    line = line.replace(' H$NGA IHOP ', ' H$NGA_IHOP ')
    line = line.replace(' H$NGA KVAR ', ' H$NGA_KVAR ')
    line = line.replace(' H$NGA MED ', ' H$NGA_MED ')
    line = line.replace(' H$NGA P@ ', ' H$NGA_P@ ')
    line = line.replace(' H$NGA SAMMAN ', ' H$NGA_SAMMAN ')
    line = line.replace(' H$NGA SIG ', ' H$NGA_SIG ')
    line = line.replace(' H$NGA TILL SIG ', ' H$NGA_TILL_SIG ')
    line = line.replace(' H$NGA UPP ', ' H$NGA_UPP ')
    line = line.replace(' H$NGA UPP SIG ', ' H$NGA_UPP_SIG ')
    line = line.replace(' H$NGA UT ', ' H$NGA_UT ')
    line = line.replace(' H$NGIVA SIG ', ' H$NGIVA_SIG ')
    line = line.replace(' H$R INNE ', ' H$R_INNE ')
    line = line.replace(' H$R NERE ', ' H$R_NERE ')
    line = line.replace(' H$R OCH D$R ', ' H$R_OCH_D$R ')
    line = line.replace(' H$R OCH VAR ', ' H$R_OCH_VAR ')
    line = line.replace(' H$R OM DAGEN ', ' H$R_OM_DAGEN ')
    line = line.replace(' H$R OM NATTEN ', ' H$R_OM_NATTEN ')
    line = line.replace(' H$R UPPE ', ' H$R_UPPE ')
    line = line.replace(' H$RDA UT ', ' H$RDA_UT ')
    line = line.replace(' H$RS OCH TV$RS ', ' H$RS_OCH_TV$RS ')
    line = line.replace(' H$RSAN OCH TV$RSAN ', ' H$RSAN_OCH_TV$RSAN ')
    line = line.replace(' H$VA I SIG ', ' H$VA_I_SIG ')
    line = line.replace(' H$VA SIG ', ' H$VA_SIG ')
    line = line.replace(' H$VA UT ', ' H$VA_UT ')
    line = line.replace(' H$VDA SIG ', ' H$VDA_SIG ')
    line = line.replace(' HA #VER ', ' HA_#VER ')
    line = line.replace(' HA AV ', ' HA_AV ')
    line = line.replace(' HA BAKOM SIG ', ' HA_BAKOM_SIG ')
    line = line.replace(' HA BORT ', ' HA_BORT ')
    line = line.replace(' HA EMELLAN ', ' HA_EMELLAN ')
    line = line.replace(' HA EMOT ', ' HA_EMOT ')
    line = line.replace(' HA F#R SIG ', ' HA_F#R_SIG ')
    line = line.replace(' HA I ', ' HA_I ')
    line = line.replace(' HA IHJ$L ', ' HA_IHJ$L ')
    line = line.replace(' HA KVAR ', ' HA_KVAR ')
    line = line.replace(' HA MED SIG ', ' HA_MED_SIG ')
    line = line.replace(' HA NED ', ' HA_NED ')
    line = line.replace(' HA NER ', ' HA_NER ')
    line = line.replace(' HA P@ SIG ', ' HA_P@_SIG ')
    line = line.replace(' HA S#NDER ', ' HA_S#NDER ')
    line = line.replace(' HA SIG ', ' HA_SIG ')
    line = line.replace(' HABILITERA SIG ', ' HABILITERA_SIG ')
    line = line.replace(' HACKA BORT ', ' HACKA_BORT ')
    line = line.replace(' HACKA S#NDER ', ' HACKA_S#NDER ')
    line = line.replace(' HACKA UPP ', ' HACKA_UPP ')
    line = line.replace(' HACKA UT ', ' HACKA_UT ')
    line = line.replace(' HAFSA #VER ', ' HAFSA_#VER ')
    line = line.replace(' HAFSA IV$G ', ' HAFSA_IV$G ')
    line = line.replace(' HAGLA NED ', ' HAGLA_NED ')
    line = line.replace(' HAJA TILL ', ' HAJA_TILL ')
    line = line.replace(' HAKA AV ', ' HAKA_AV ')
    line = line.replace(' HAKA FAST ', ' HAKA_FAST ')
    line = line.replace(' HAKA I ', ' HAKA_I ')
    line = line.replace(' HAKA LOSS ', ' HAKA_LOSS ')
    line = line.replace(' HAKA P@ ', ' HAKA_P@ ')
    line = line.replace(' HAKA SIG ', ' HAKA_SIG ')
    line = line.replace(' HAKA UPP ', ' HAKA_UPP ')
    line = line.replace(' HAKA UPP SIG ', ' HAKA_UPP_SIG ')
    line = line.replace(' HALA HEM ', ' HALA_HEM ')
    line = line.replace(' HALA IN ', ' HALA_IN ')
    line = line.replace(' HALA NED ', ' HALA_NED ')
    line = line.replace(' HALA NER ', ' HALA_NER ')
    line = line.replace(' HALA OMBORD ', ' HALA_OMBORD ')
    line = line.replace(' HALA UPP ', ' HALA_UPP ')
    line = line.replace(' HALA UT P@ ', ' HALA_UT_P@ ')
    line = line.replace(' HALKA #VER ', ' HALKA_#VER ')
    line = line.replace(' HALKA AV ', ' HALKA_AV ')
    line = line.replace(' HALKA NED ', ' HALKA_NED ')
    line = line.replace(' HALKA NER ', ' HALKA_NER ')
    line = line.replace(' HALKA OMKULL ', ' HALKA_OMKULL ')
    line = line.replace(' HARKLA SIG ', ' HARKLA_SIG ')
    line = line.replace(' HARSKLA SIG ', ' HARSKLA_SIG ')
    line = line.replace(' HASA NER ', ' HASA_NER ')
    line = line.replace(' HASA SIG ', ' HASA_SIG ')
    line = line.replace(' HASA SIG FRAM ', ' HASA_SIG_FRAM ')
    line = line.replace(' HASPLA UR SIG ', ' HASPLA_UR_SIG ')
    line = line.replace(' HAUSSA UPP ', ' HAUSSA_UPP ')
    line = line.replace(' HEJA P@ ', ' HEJA_P@ ')
    line = line.replace(' HEJDA SIG ', ' HEJDA_SIG ')
    line = line.replace(' HETSA UPP SIG ', ' HETSA_UPP_SIG ')
    line = line.replace(' HETTA UPP ', ' HETTA_UPP ')
    line = line.replace(' HIMLA SIG ', ' HIMLA_SIG ')
    line = line.replace(' HIN H@LE ', ' HIN_H@LE ')
    line = line.replace(' HINKA UPP ', ' HINKA_UPP ')
    line = line.replace(' HINNA F#RE ', ' HINNA_F#RE ')
    line = line.replace(' HINNA F#RST ', ' HINNA_F#RST ')
    line = line.replace(' HINNA FATT ', ' HINNA_FATT ')
    line = line.replace(' HINNA MED ', ' HINNA_MED ')
    line = line.replace(' HINNA UNDAN ', ' HINNA_UNDAN ')
    line = line.replace(' HINNA UPP ', ' HINNA_UPP ')
    line = line.replace(' HISSA UPP ', ' HISSA_UPP ')
    line = line.replace(' HITTA P@ ', ' HITTA_P@ ')
    line = line.replace(' HIVA IV$G ', ' HIVA_IV$G ')
    line = line.replace(' HJ$LPA TILL ', ' HJ$LPA_TILL ')
    line = line.replace(' HJ$LPA UPP ', ' HJ$LPA_UPP ')
    line = line.replace(' HOLKA UR ', ' HOLKA_UR ')
    line = line.replace(' HOPA SIG ', ' HOPA_SIG ')
    line = line.replace(' HOPPA #VER ', ' HOPPA_#VER ')
    line = line.replace(' HOPPA AV ', ' HOPPA_AV ')
    line = line.replace(' HOPPA IN ', ' HOPPA_IN ')
    line = line.replace(' HOPPA NER ', ' HOPPA_NER ')
    line = line.replace(' HOPPA P@ ', ' HOPPA_P@ ')
    line = line.replace(' HOPPA TILL ', ' HOPPA_TILL ')
    line = line.replace(' HOPPA UPP ', ' HOPPA_UPP ')
    line = line.replace(' HOSTA UPP ', ' HOSTA_UPP ')
    line = line.replace(' HOVERA SIG ', ' HOVERA_SIG ')
    line = line.replace(' HUGGA AV ', ' HUGGA_AV ')
    line = line.replace(' HUGGA I ', ' HUGGA_I ')
    line = line.replace(' HUGGA IN ', ' HUGGA_IN ')
    line = line.replace(' HUGGA NER ', ' HUGGA_NER ')
    line = line.replace(' HUGGA TAG ', ' HUGGA_TAG ')
    line = line.replace(' HUGGA TILL ', ' HUGGA_TILL ')
    line = line.replace(' HUGGA TILL MED ', ' HUGGA_TILL_MED ')
    line = line.replace(' HUKA SIG ', ' HUKA_SIG ')
    line = line.replace(' HULLER OM BULLER ', ' HULLER_OM_BULLER ')
    line = line.replace(' HUR S@ ', ' HUR_S@ ')
    line = line.replace(' HUR SOM HELST ', ' HUR_SOM_HELST ')
    line = line.replace(' HUX FLUX ', ' HUX_FLUX ')
    line = line.replace(' HYFSA TILL ', ' HYFSA_TILL ')
    line = line.replace(' HYRA IN ', ' HYRA_IN ')
    line = line.replace(' HYRA IN SIG ', ' HYRA_IN_SIG ')
    line = line.replace(' HYRA UT ', ' HYRA_UT ')
    line = line.replace(' HYSA IN ', ' HYSA_IN ')
    line = line.replace(' HYSCHA NER ', ' HYSCHA_NER ')
    line = line.replace(' I AKT ', ' I_AKT ')
    line = line.replace(' I DAG ', ' I_DAG ')
    line = line.replace(' I ETT ', ' I_ETT ')
    line = line.replace(' I FALL ', ' I_FALL ')
    line = line.replace(' I FATT ', ' I_FATT ')
    line = line.replace(' I FJOL ', ' I_FJOL ')
    line = line.replace(' I FJOR ', ' I_FJOR ')
    line = line.replace(' I FR@GA ', ' I_FR@GA ')
    line = line.replace(' I FRED ', ' I_FRED ')
    line = line.replace(' I G@NG ', ' I_G@NG ')
    line = line.replace(' I G@R ', ' I_G@R ')
    line = line.replace(' I JONS ', ' I_JONS ')
    line = line.replace(' I KAPP ', ' I_KAPP ')
    line = line.replace(' I KLYV ', ' I_KLYV ')
    line = line.replace(' I KRAFT ', ' I_KRAFT ')
    line = line.replace(' I KV$LL ', ' I_KV$LL ')
    line = line.replace(' I LAG ', ' I_LAG ')
    line = line.replace(' I LAND ', ' I_LAND ')
    line = line.replace(' I MORGON ', ' I_MORGON ')
    line = line.replace(' I S$NDER ', ' I_S$NDER ')
    line = line.replace(' I S$R ', ' I_S$R ')
    line = line.replace(' I ST@ND ', ' I_ST@ND ')
    line = line.replace(' I ST$LLET ', ' I_ST$LLET ')
    line = line.replace(' I TAGET ', ' I_TAGET ')
    line = line.replace(' I TOPPINDEX ', ' I_TOPPINDEX ')
    line = line.replace(' IDENTIFIERA SIG ', ' IDENTIFIERA_SIG ')
    line = line.replace(' IF#RA SIG ', ' IF#RA_SIG ')
    line = line.replace(' IKL$DA SIG ', ' IKL$DA_SIG ')
    line = line.replace(' ILA FRAM ', ' ILA_FRAM ')
    line = line.replace(' ILSKNA TILL ', ' ILSKNA_TILL ')
    line = line.replace(' IMMA IGEN ', ' IMMA_IGEN ')
    line = line.replace(' IMMA SIG ', ' IMMA_SIG ')
    line = line.replace(' IN ABSURDUM ', ' IN_ABSURDUM ')
    line = line.replace(' IN EMOT ', ' IN_EMOT ')
    line = line.replace(' IN IGENOM ', ' IN_IGENOM ')
    line = line.replace(' IN SPE ', ' IN_SPE ')
    line = line.replace(' INBILLA SIG ', ' INBILLA_SIG ')
    line = line.replace(' INFINNA SIG ', ' INFINNA_SIG ')
    line = line.replace(' INGEN VART ', ' INGEN_VART ')
    line = line.replace(' INKAPSLA SIG ', ' INKAPSLA_SIG ')
    line = line.replace(' INL@TA SIG ', ' INL@TA_SIG ')
    line = line.replace(' INN$STLA SIG ', ' INN$STLA_SIG ')
    line = line.replace(' INORDNA SIG ', ' INORDNA_SIG ')
    line = line.replace(' INRIKTA SIG ', ' INRIKTA_SIG ')
    line = line.replace(' INSKR$NKA SIG ', ' INSKR$NKA_SIG ')
    line = line.replace(' INSMICKRA SIG ', ' INSMICKRA_SIG ')
    line = line.replace(' INSMYGA SIG ', ' INSMYGA_SIG ')
    line = line.replace(' INST$LLA SIG ', ' INST$LLA_SIG ')
    line = line.replace(' INSTALLERA SIG ', ' INSTALLERA_SIG ')
    line = line.replace(' INVECKLA SIG ', ' INVECKLA_SIG ')
    line = line.replace(' IRRITERA SIG ', ' IRRITERA_SIG ')
    line = line.replace(' J$KTA P@ ', ' J$KTA_P@ ')
    line = line.replace(' J$MKA IHOP ', ' J$MKA_IHOP ')
    line = line.replace(' J$MNA AV ', ' J$MNA_AV ')
    line = line.replace(' J$MNA TILL ', ' J$MNA_TILL ')
    line = line.replace(' J$MNA UT ', ' J$MNA_UT ')
    line = line.replace(' J$MRA SIG ', ' J$MRA_SIG ')
    line = line.replace(' J$SA #VER ', ' J$SA_#VER ')
    line = line.replace(' J$SA UPP ', ' J$SA_UPP ')
    line = line.replace(' J$SA UT ', ' J$SA_UT ')
    line = line.replace(' JAGA BORT ', ' JAGA_BORT ')
    line = line.replace(' JAGA FRAM ', ' JAGA_FRAM ')
    line = line.replace(' JAGA IN ', ' JAGA_IN ')
    line = line.replace(' JAGA UPP ', ' JAGA_UPP ')
    line = line.replace(' JAGA UT ', ' JAGA_UT ')
    line = line.replace(' JAMSA MED ', ' JAMSA_MED ')
    line = line.replace(' JAZZA UPP ', ' JAZZA_UPP ')
    line = line.replace(' JO DU ', ' JO_DU ')
    line = line.replace(' JOBBA #VER ', ' JOBBA_#VER ')
    line = line.replace(' JUR KAND ', ' JUR_KAND ')
    line = line.replace(' K@DA NER SIG ', ' K@DA_NER_SIG ')
    line = line.replace(' K#A UPP ', ' K#A_UPP ')
    line = line.replace(' K#PA HEM ', ' K#PA_HEM ')
    line = line.replace(' K#PA IN ', ' K#PA_IN ')
    line = line.replace(' K#PA SIG ', ' K#PA_SIG ')
    line = line.replace(' K#PA UPP ', ' K#PA_UPP ')
    line = line.replace(' K#PA UT ', ' K#PA_UT ')
    line = line.replace(' K#RA BORT ', ' K#RA_BORT ')
    line = line.replace(' K#RA FRAM ', ' K#RA_FRAM ')
    line = line.replace(' K#RA IN ', ' K#RA_IN ')
    line = line.replace(' K#RA UPP ', ' K#RA_UPP ')
    line = line.replace(' K#RA UT ', ' K#RA_UT ')
    line = line.replace(' K$BBLA MOT ', ' K$BBLA_MOT ')
    line = line.replace(' K$KA UPP ', ' K$KA_UPP ')
    line = line.replace(' K$MPA MOT ', ' K$MPA_MOT ')
    line = line.replace(' K$MPA SIG UPP ', ' K$MPA_SIG_UPP ')
    line = line.replace(' K$MPA VIDARE ', ' K$MPA_VIDARE ')
    line = line.replace(' K$NNA AV ', ' K$NNA_AV ')
    line = line.replace(' K$NNA EFTER ', ' K$NNA_EFTER ')
    line = line.replace(' K$NNA IGEN ', ' K$NNA_IGEN ')
    line = line.replace(' K$NNA IN ', ' K$NNA_IN ')
    line = line.replace(' K$NNA P@ ', ' K$NNA_P@ ')
    line = line.replace(' K$NNA SIG ', ' K$NNA_SIG ')
    line = line.replace(' K$NNA SIG F#R ', ' K$NNA_SIG_F#R ')
    line = line.replace(' K$NNA TILL ', ' K$NNA_TILL ')
    line = line.replace(' K$NNAS VID ', ' K$NNAS_VID ')
    line = line.replace(' K$RNA UR ', ' K$RNA_UR ')
    line = line.replace(' K$RVA TILL SIG ', ' K$RVA_TILL_SIG ')
    line = line.replace(' KAJKA RUNT ', ' KAJKA_RUNT ')
    line = line.replace(' KALLA FRAM ', ' KALLA_FRAM ')
    line = line.replace(' KALLA IN ', ' KALLA_IN ')
    line = line.replace(' KALLA SAMMAN ', ' KALLA_SAMMAN ')
    line = line.replace(' KALLA UPP ', ' KALLA_UPP ')
    line = line.replace(' KALLA UT ', ' KALLA_UT ')
    line = line.replace(' KAMMA HEM ', ' KAMMA_HEM ')
    line = line.replace(' KAMMA UT ', ' KAMMA_UT ')
    line = line.replace(' KANA IV$G ', ' KANA_IV$G ')
    line = line.replace(' KANA UNDAN ', ' KANA_UNDAN ')
    line = line.replace(' KAPA AV ', ' KAPA_AV ')
    line = line.replace(' KAPSLA IN ', ' KAPSLA_IN ')
    line = line.replace(' KASSERA IN ', ' KASSERA_IN ')
    line = line.replace(' KASTA @T ', ' KASTA_@T ')
    line = line.replace(' KASTA #VER ', ' KASTA_#VER ')
    line = line.replace(' KASTA AV ', ' KASTA_AV ')
    line = line.replace(' KASTA AV SIG ', ' KASTA_AV_SIG ')
    line = line.replace(' KASTA BORT ', ' KASTA_BORT ')
    line = line.replace(' KASTA I SIG ', ' KASTA_I_SIG ')
    line = line.replace(' KASTA IFR@N SIG ', ' KASTA_IFR@N_SIG ')
    line = line.replace(' KASTA IN ', ' KASTA_IN ')
    line = line.replace(' KASTA LOSS ', ' KASTA_LOSS ')
    line = line.replace(' KASTA NED ', ' KASTA_NED ')
    line = line.replace(' KASTA OM ', ' KASTA_OM ')
    line = line.replace(' KASTA SIG UT ', ' KASTA_SIG_UT ')
    line = line.replace(' KASTA SIG ', ' KASTA_SIG ')
    line = line.replace(' KASTA UPP ', ' KASTA_UPP ')
    line = line.replace(' KASTA UT ', ' KASTA_UT ')
    line = line.replace(' KASTADE SIG UT ', ' KASTADE_SIG_UT ')
    line = line.replace(' KASTADE SIG ', ' KASTADE_SIG ')
    line = line.replace(' KAVA SIG ', ' KAVA_SIG ')
    line = line.replace(' KAVA UPP ', ' KAVA_UPP ')
    line = line.replace(' KAVLA UPP ', ' KAVLA_UPP ')
    line = line.replace(' KAXA UPP SIG ', ' KAXA_UPP_SIG ')
    line = line.replace(' KEDJA FAST ', ' KEDJA_FAST ')
    line = line.replace(' KIKA FRAM ', ' KIKA_FRAM ')
    line = line.replace(' KIKA IN ', ' KIKA_IN ')
    line = line.replace(' KIKA UT ', ' KIKA_UT ')
    line = line.replace(' KILA IN ', ' KILA_IN ')
    line = line.replace(' KIRRA SIG ', ' KIRRA_SIG ')
    line = line.replace(' KISSA NER SIG ', ' KISSA_NER_SIG ')
    line = line.replace(' KISSA P@ SIG ', ' KISSA_P@_SIG ')
    line = line.replace(' KITTA IGEN ', ' KITTA_IGEN ')
    line = line.replace(' KL@ UPP ', ' KL@_UPP ')
    line = line.replace(' KL$ P@ ', ' KL$_P@ ')
    line = line.replace(' KL$ UPP ', ' KL$_UPP ')
    line = line.replace(' KL$ UT SIG ', ' KL$_UT_SIG ')
    line = line.replace(' KL$CKA UR SIG ', ' KL$CKA_UR_SIG ')
    line = line.replace(' KL$MMA @T ', ' KL$MMA_@T ')
    line = line.replace(' KL$MMA IN ', ' KL$MMA_IN ')
    line = line.replace(' KL$MMA UT ', ' KL$MMA_UT ')
    line = line.replace(' KL$NGA SIG FAST ', ' KL$NGA_SIG_FAST ')
    line = line.replace(' KL$TTRA NED ', ' KL$TTRA_NED ')
    line = line.replace(' KL$TTRA UPP ', ' KL$TTRA_UPP ')
    line = line.replace(' KLADDA NER ', ' KLADDA_NER ')
    line = line.replace(' KLAMPA IN ', ' KLAMPA_IN ')
    line = line.replace(' KLAMRA SIG FAST ', ' KLAMRA_SIG_FAST ')
    line = line.replace(' KLANTA SIG ', ' KLANTA_SIG ')
    line = line.replace(' KLANTA TILL ', ' KLANTA_TILL ')
    line = line.replace(' KLAPPA IGEN ', ' KLAPPA_IGEN ')
    line = line.replace(' KLAPPA IGENOM ', ' KLAPPA_IGENOM ')
    line = line.replace(' KLAPPA IHOP ', ' KLAPPA_IHOP ')
    line = line.replace(' KLAPPA TILL ', ' KLAPPA_TILL ')
    line = line.replace(' KLARA AV ', ' KLARA_AV ')
    line = line.replace(' KLARA SIG ', ' KLARA_SIG ')
    line = line.replace(' KLARA UPP ', ' KLARA_UPP ')
    line = line.replace(' KLARA UT ', ' KLARA_UT ')
    line = line.replace(' KLARNA UPP ', ' KLARNA_UPP ')
    line = line.replace(' KLEMA BORT ', ' KLEMA_BORT ')
    line = line.replace(' KLETA NER SIG ', ' KLETA_NER_SIG ')
    line = line.replace(' KLETA UT ', ' KLETA_UT ')
    line = line.replace(' KLIA SIG ', ' KLIA_SIG ')
    line = line.replace(' KLIBBA FAST ', ' KLIBBA_FAST ')
    line = line.replace(' KLIMPA SIG ', ' KLIMPA_SIG ')
    line = line.replace(' KLINGA AV ', ' KLINGA_AV ')
    line = line.replace(' KLINGA UT ', ' KLINGA_UT ')
    line = line.replace(' KLIPPA AV ', ' KLIPPA_AV ')
    line = line.replace(' KLIPPA S#NDER ', ' KLIPPA_S#NDER ')
    line = line.replace(' KLIPPA SIG ', ' KLIPPA_SIG ')
    line = line.replace(' KLIPPA TILL ', ' KLIPPA_TILL ')
    line = line.replace(' KLIPPA UPP ', ' KLIPPA_UPP ')
    line = line.replace(' KLIPPA UT ', ' KLIPPA_UT ')
    line = line.replace(' KLISTRA IGEN ', ' KLISTRA_IGEN ')
    line = line.replace(' KLISTRA IN ', ' KLISTRA_IN ')
    line = line.replace(' KLISTRA UPP ', ' KLISTRA_UPP ')
    line = line.replace(' KLIVA FRAM ', ' KLIVA_FRAM ')
    line = line.replace(' KLIVA UPP ', ' KLIVA_UPP ')
    line = line.replace(' KLOTTRA NED ', ' KLOTTRA_NED ')
    line = line.replace(' KLUBBA NED ', ' KLUBBA_NED ')
    line = line.replace(' KLUDDA NED ', ' KLUDDA_NED ')
    line = line.replace(' KLUMPA IHOP ', ' KLUMPA_IHOP ')
    line = line.replace(' KLUMPA SIG ', ' KLUMPA_SIG ')
    line = line.replace(' KLUNGA SIG ', ' KLUNGA_SIG ')
    line = line.replace(' KLUNKA I SIG ', ' KLUNKA_I_SIG ')
    line = line.replace(' KLUNSA SIG ', ' KLUNSA_SIG ')
    line = line.replace(' KLURA UT ', ' KLURA_UT ')
    line = line.replace(' KLUTA UT SIG ', ' KLUTA_UT_SIG ')
    line = line.replace(' KLYFTA SIG ', ' KLYFTA_SIG ')
    line = line.replace(' KLYVA SIG ', ' KLYVA_SIG ')
    line = line.replace(' KN@DA UT ', ' KN@DA_UT ')
    line = line.replace(' KN@PA IHOP ', ' KN@PA_IHOP ')
    line = line.replace(' KN@PA SIG ', ' KN@PA_SIG ')
    line = line.replace(' KN#LA IHOP ', ' KN#LA_IHOP ')
    line = line.replace(' KN#LA SIG ', ' KN#LA_SIG ')
    line = line.replace(' KN#LA TILL ', ' KN#LA_TILL ')
    line = line.replace(' KN$PPA AV ', ' KN$PPA_AV ')
    line = line.replace(' KN$PPA H$NDERNA ', ' KN$PPA_H$NDERNA ')
    line = line.replace(' KN$PPA IGEN ', ' KN$PPA_IGEN ')
    line = line.replace(' KN$PPA IHOP ', ' KN$PPA_IHOP ')
    line = line.replace(' KN$PPA NED ', ' KN$PPA_NED ')
    line = line.replace(' KN$PPA P@ ', ' KN$PPA_P@ ')
    line = line.replace(' KN$PPA TILL ', ' KN$PPA_TILL ')
    line = line.replace(' KN$PPA UPP ', ' KN$PPA_UPP ')
    line = line.replace(' KNACKA AV ', ' KNACKA_AV ')
    line = line.replace(' KNACKA P@ ', ' KNACKA_P@ ')
    line = line.replace(' KNACKA UT ', ' KNACKA_UT ')
    line = line.replace(' KNAPRA I SIG ', ' KNAPRA_I_SIG ')
    line = line.replace(' KNIPA @T ', ' KNIPA_@T ')
    line = line.replace(' KNIPA AV ', ' KNIPA_AV ')
    line = line.replace(' KNIPA IHOP ', ' KNIPA_IHOP ')
    line = line.replace(' KNIPSA AV ', ' KNIPSA_AV ')
    line = line.replace(' KNOLLRA SIG ', ' KNOLLRA_SIG ')
    line = line.replace(' KNORRA SIG ', ' KNORRA_SIG ')
    line = line.replace(' KNORVA TILL ', ' KNORVA_TILL ')
    line = line.replace(' KNOTTRA SIG ', ' KNOTTRA_SIG ')
    line = line.replace(' KNOW HOW ', ' KNOW_HOW ')
    line = line.replace(' KNUFFA FRAM ', ' KNUFFA_FRAM ')
    line = line.replace(' KNUFFA IN ', ' KNUFFA_IN ')
    line = line.replace(' KNUFFA NED ', ' KNUFFA_NED ')
    line = line.replace(' KNUFFA OMKULL ', ' KNUFFA_OMKULL ')
    line = line.replace(' KNUFFA TILL ', ' KNUFFA_TILL ')
    line = line.replace(' KNUFFA UNDAN ', ' KNUFFA_UNDAN ')
    line = line.replace(' KNUFFA UPP ', ' KNUFFA_UPP ')
    line = line.replace(' KNYCKA TILL ', ' KNYCKA_TILL ')
    line = line.replace(' KNYCKLA IHOP ', ' KNYCKLA_IHOP ')
    line = line.replace(' KNYCKLA SAMMAN ', ' KNYCKLA_SAMMAN ')
    line = line.replace(' KNYCKLA TILL ', ' KNYCKLA_TILL ')
    line = line.replace(' KNYTA @T ', ' KNYTA_@T ')
    line = line.replace(' KNYTA AN ', ' KNYTA_AN ')
    line = line.replace(' KNYTA FAST ', ' KNYTA_FAST ')
    line = line.replace(' KNYTA IHOP ', ' KNYTA_IHOP ')
    line = line.replace(' KNYTA OM ', ' KNYTA_OM ')
    line = line.replace(' KNYTA SAMMAN ', ' KNYTA_SAMMAN ')
    line = line.replace(' KNYTA SIG ', ' KNYTA_SIG ')
    line = line.replace(' KNYTA TILL ', ' KNYTA_TILL ')
    line = line.replace(' KNYTA UPP ', ' KNYTA_UPP ')
    line = line.replace(' KOKA IN ', ' KOKA_IN ')
    line = line.replace(' KOKA UPP ', ' KOKA_UPP ')
    line = line.replace(' KOLA AV ', ' KOLA_AV ')
    line = line.replace(' KOLKA I SIG ', ' KOLKA_I_SIG ')
    line = line.replace(' KOLLA IN ', ' KOLLA_IN ')
    line = line.replace(' KOLLA UPP ', ' KOLLA_UPP ')
    line = line.replace(' KOLLRA BORT ', ' KOLLRA_BORT ')
    line = line.replace(' KOLPORTERA UT ', ' KOLPORTERA_UT ')
    line = line.replace(' KOMMA AV SIG ', ' KOMMA_AV_SIG ')
    line = line.replace(' KOMMA BORT ', ' KOMMA_BORT ')
    line = line.replace(' KOMMA HEM ', ' KOMMA_HEM ')
    line = line.replace(' KOMMA IFR@GA ', ' KOMMA_IFR@GA ')
    line = line.replace(' KOMMA IH@G ', ' KOMMA_IH@G ')
    line = line.replace(' KOMMA IN ', ' KOMMA_IN ')
    line = line.replace(' KOMMA NED ', ' KOMMA_NED ')
    line = line.replace(' KOMMA P@ ', ' KOMMA_P@ ')
    line = line.replace(' KOMMA SIG ', ' KOMMA_SIG ')
    line = line.replace(' KOMMA TILL ', ' KOMMA_TILL ')
    line = line.replace(' KOMMA UR ', ' KOMMA_UR ')
    line = line.replace(' KOMMA UT ', ' KOMMA_UT ')
    line = line.replace(' KONCENTRERA SIG ', ' KONCENTRERA_SIG ')
    line = line.replace(' KOPIERA IN ', ' KOPIERA_IN ')
    line = line.replace(' KOPPLA AV ', ' KOPPLA_AV ')
    line = line.replace(' KOPPLA BORT ', ' KOPPLA_BORT ')
    line = line.replace(' KOPPLA IHOP ', ' KOPPLA_IHOP ')
    line = line.replace(' KOPPLA IN ', ' KOPPLA_IN ')
    line = line.replace(' KOPPLA P@ ', ' KOPPLA_P@ ')
    line = line.replace(' KOPPLA TILL ', ' KOPPLA_TILL ')
    line = line.replace(' KORKA IGEN ', ' KORKA_IGEN ')
    line = line.replace(' KORKA UPP ', ' KORKA_UPP ')
    line = line.replace(' KORSA SIG ', ' KORSA_SIG ')
    line = line.replace(' KORTA NER ', ' KORTA_NER ')
    line = line.replace(' KORVA SIG ', ' KORVA_SIG ')
    line = line.replace(' KOSTA P@ ', ' KOSTA_P@ ')
    line = line.replace(' KR@MA SIG ', ' KR@MA_SIG ')
    line = line.replace(' KR@NGLA SIG ', ' KR@NGLA_SIG ')
    line = line.replace(' KR@NGLA TILL ', ' KR@NGLA_TILL ')
    line = line.replace(' KR#KA SIG ', ' KR#KA_SIG ')
    line = line.replace(' KR$KAS UPP ', ' KR$KAS_UPP ')
    line = line.replace(' KR$NGA AV SIG ', ' KR$NGA_AV_SIG ')
    line = line.replace(' KR$NGA P@ ', ' KR$NGA_P@ ')
    line = line.replace(' KR$NGA TILL ', ' KR$NGA_TILL ')
    line = line.replace(' KR$VA IGEN ', ' KR$VA_IGEN ')
    line = line.replace(' KR$VA IN ', ' KR$VA_IN ')
    line = line.replace(' KR$VA TILLBAKS ', ' KR$VA_TILLBAKS ')
    line = line.replace(' KR$VA UT ', ' KR$VA_UT ')
    line = line.replace(' KRAFSA UPP ', ' KRAFSA_UPP ')
    line = line.replace(' KRAMA IHJ$L ', ' KRAMA_IHJ$L ')
    line = line.replace(' KRAMA IHOP ', ' KRAMA_IHOP ')
    line = line.replace(' KRAMA OM ', ' KRAMA_OM ')
    line = line.replace(' KRAMA UR ', ' KRAMA_UR ')
    line = line.replace(' KRAMA UT ', ' KRAMA_UT ')
    line = line.replace(' KRATSA UR ', ' KRATSA_UR ')
    line = line.replace(' KRETSA RUNT ', ' KRETSA_RUNT ')
    line = line.replace(' KROKA AV ', ' KROKA_AV ')
    line = line.replace(' KROKA FAST ', ' KROKA_FAST ')
    line = line.replace(' KROKA P@ ', ' KROKA_P@ ')
    line = line.replace(' KROMA SIG ', ' KROMA_SIG ')
    line = line.replace(' KRULLA SIG ', ' KRULLA_SIG ')
    line = line.replace(' KRUMBUKTA SIG ', ' KRUMBUKTA_SIG ')
    line = line.replace(' KRUTA P@ ', ' KRUTA_P@ ')
    line = line.replace(' KRYA P@ SIG ', ' KRYA_P@_SIG ')
    line = line.replace(' KRYMPA IHOP ', ' KRYMPA_IHOP ')
    line = line.replace(' KRYMPA NED ', ' KRYMPA_NED ')
    line = line.replace(' KRYMPA SAMMAN ', ' KRYMPA_SAMMAN ')
    line = line.replace(' KRYPA IHOP ', ' KRYPA_IHOP ')
    line = line.replace(' KRYPA IN ', ' KRYPA_IN ')
    line = line.replace(' KRYPA NED ', ' KRYPA_NED ')
    line = line.replace(' KRYPA UR ', ' KRYPA_UR ')
    line = line.replace(' KRYSSA F#R ', ' KRYSSA_F#R ')
    line = line.replace(' KRYSTA FRAM ', ' KRYSTA_FRAM ')
    line = line.replace(' KRYSTA UT ', ' KRYSTA_UT ')
    line = line.replace(' KULLRA SIG ', ' KULLRA_SIG ')
    line = line.replace(' KURA IHOP SIG ', ' KURA_IHOP_SIG ')
    line = line.replace(' KUSKA OMKRING ', ' KUSKA_OMKRING ')
    line = line.replace(' KUSKA RUNT ', ' KUSKA_RUNT ')
    line = line.replace(' KUTA IV$G ', ' KUTA_IV$G ')
    line = line.replace(' KUTA OMKRING ', ' KUTA_OMKRING ')
    line = line.replace(' KVALA IN ', ' KVALA_IN ')
    line = line.replace(' KVALIFICERA SIG ', ' KVALIFICERA_SIG ')
    line = line.replace(' KVICKA P@ ', ' KVICKA_P@ ')
    line = line.replace(' KVICKA SIG ', ' KVICKA_SIG ')
    line = line.replace(' KVICKNA TILL ', ' KVICKNA_TILL ')
    line = line.replace(' KVITTERA IN ', ' KVITTERA_IN ')
    line = line.replace(' KYLA AV ', ' KYLA_AV ')
    line = line.replace(' KYLA NED ', ' KYLA_NED ')
    line = line.replace(' KYLA NER ', ' KYLA_NER ')
    line = line.replace(' KYLA UT ', ' KYLA_UT ')
    line = line.replace(' KYLSA IHOP SIG ', ' KYLSA_IHOP_SIG ')
    line = line.replace(' KYLSA SIG ', ' KYLSA_SIG ')
    line = line.replace(' L@DA VID ', ' L@DA_VID ')
    line = line.replace(' L@NA BORT ', ' L@NA_BORT ')
    line = line.replace(' L@NA IN ', ' L@NA_IN ')
    line = line.replace(' L@NA UPP ', ' L@NA_UPP ')
    line = line.replace(' L@NA UT ', ' L@NA_UT ')
    line = line.replace(' L@SA FAST ', ' L@SA_FAST ')
    line = line.replace(' L@SA IN ', ' L@SA_IN ')
    line = line.replace(' L@SA SIG ', ' L@SA_SIG ')
    line = line.replace(' L@SA UPP ', ' L@SA_UPP ')
    line = line.replace(' L@SA UTE ', ' L@SA_UTE ')
    line = line.replace(' L@TA BLI ', ' L@TA_BLI ')
    line = line.replace(' L@TA SIG LURAS ', ' L@TA_SIG_LURAS ')
    line = line.replace(' L#DA FAST ', ' L#DA_FAST ')
    line = line.replace(' L#DA SAMMAN ', ' L#DA_SAMMAN ')
    line = line.replace(' L#DDRA SIG ', ' L#DDRA_SIG ')
    line = line.replace(' L#GA SIG ', ' L#GA_SIG ')
    line = line.replace(' L#MSKNA TILL ', ' L#MSKNA_TILL ')
    line = line.replace(' L#NA SIG ', ' L#NA_SIG ')
    line = line.replace(' L#PA AMOK ', ' L#PA_AMOK ')
    line = line.replace(' L#PA IN ', ' L#PA_IN ')
    line = line.replace(' L#PA SAMMAN ', ' L#PA_SAMMAN ')
    line = line.replace(' L#PA UT ', ' L#PA_UT ')
    line = line.replace(' L#SA IN ', ' L#SA_IN ')
    line = line.replace(' L#SA SIG ', ' L#SA_SIG ')
    line = line.replace(' L#SA UPP ', ' L#SA_UPP ')
    line = line.replace(' L#SA UT ', ' L#SA_UT ')
    line = line.replace(' L#SKA SIG ', ' L#SKA_SIG ')
    line = line.replace(' L$CKA UT ', ' L$CKA_UT ')
    line = line.replace(' L$GGA AN ', ' L$GGA_AN ')
    line = line.replace(' L$GGA AV ', ' L$GGA_AV ')
    line = line.replace(' L$GGA BORT ', ' L$GGA_BORT ')
    line = line.replace(' L$GGA FRAM ', ' L$GGA_FRAM ')
    line = line.replace(' L$GGA I ', ' L$GGA_I ')
    line = line.replace(' L$GGA IN ', ' L$GGA_IN ')
    line = line.replace(' L$GGA NED ', ' L$GGA_NED ')
    line = line.replace(' L$GGA NER ', ' L$GGA_NER ')
    line = line.replace(' L$GGA SIG ', ' L$GGA_SIG ')
    line = line.replace(' L$GGA SIG I ', ' L$GGA_SIG_I ')
    line = line.replace(' L$GGA TILL ', ' L$GGA_TILL ')
    line = line.replace(' L$GGA UPP ', ' L$GGA_UPP ')
    line = line.replace(' L$GGA UT ', ' L$GGA_UT ')
    line = line.replace(' L$GRA SIG ', ' L$GRA_SIG ')
    line = line.replace(' L$KA UT ', ' L$KA_UT ')
    line = line.replace(' L$MNA AV ', ' L$MNA_AV ')
    line = line.replace(' L$MNA BORT ', ' L$MNA_BORT ')
    line = line.replace(' L$MNA FRAM ', ' L$MNA_FRAM ')
    line = line.replace(' L$MNA IGEN ', ' L$MNA_IGEN ')
    line = line.replace(' L$MNA IN ', ' L$MNA_IN ')
    line = line.replace(' L$MNA KVAR ', ' L$MNA_KVAR ')
    line = line.replace(' L$MNA TILLBAKA ', ' L$MNA_TILLBAKA ')
    line = line.replace(' L$MNA UT ', ' L$MNA_UT ')
    line = line.replace(' L$MPA AV ', ' L$MPA_AV ')
    line = line.replace(' L$MPA SIG ', ' L$MPA_SIG ')
    line = line.replace(' L$NGA SIG ', ' L$NGA_SIG ')
    line = line.replace(' L$NGTA BORT ', ' L$NGTA_BORT ')
    line = line.replace(' L$NGTA UT ', ' L$NGTA_UT ')
    line = line.replace(' L$NKA IHOP ', ' L$NKA_IHOP ')
    line = line.replace(' L$NKA SAMMAN ', ' L$NKA_SAMMAN ')
    line = line.replace(' L$RA IN ', ' L$RA_IN ')
    line = line.replace(' L$RA SIG ', ' L$RA_SIG ')
    line = line.replace(' L$RA UPP ', ' L$RA_UPP ')
    line = line.replace(' L$RA UT ', ' L$RA_UT ')
    line = line.replace(' L$SA AV ', ' L$SA_AV ')
    line = line.replace(' L$SA EMOT ', ' L$SA_EMOT ')
    line = line.replace(' L$SA IN ', ' L$SA_IN ')
    line = line.replace(' L$SA P@ ', ' L$SA_P@ ')
    line = line.replace(' L$SA UPP ', ' L$SA_UPP ')
    line = line.replace(' L$SKA SIG ', ' L$SKA_SIG ')
    line = line.replace(' L$STA UT ', ' L$STA_UT ')
    line = line.replace(' L$TTA SIG ', ' L$TTA_SIG ')
    line = line.replace(' L$XA UPP ', ' L$XA_UPP ')
    line = line.replace(' LADDA OM ', ' LADDA_OM ')
    line = line.replace(' LADDA UPP ', ' LADDA_UPP ')
    line = line.replace(' LADDA UR ', ' LADDA_UR ')
    line = line.replace(' LAGA MAT ', ' LAGA_MAT ')
    line = line.replace(' LAGA SIG IV$G ', ' LAGA_SIG_IV$G ')
    line = line.replace(' LAGA TILL ', ' LAGA_TILL ')
    line = line.replace(' LAGRA SIG ', ' LAGRA_SIG ')
    line = line.replace(' LAGRA UPP ', ' LAGRA_UPP ')
    line = line.replace(' LAKA UR ', ' LAKA_UR ')
    line = line.replace(' LAKA UT ', ' LAKA_UT ')
    line = line.replace(' LAPA I SIG ', ' LAPA_I_SIG ')
    line = line.replace(' LAPPA IHOP ', ' LAPPA_IHOP ')
    line = line.replace(' LARVA IV$G ', ' LARVA_IV$G ')
    line = line.replace(' LARVA SIG ', ' LARVA_SIG ')
    line = line.replace(' LASSA P@ ', ' LASSA_P@ ')
    line = line.replace(' LASTA AV ', ' LASTA_AV ')
    line = line.replace(' LASTA IN ', ' LASTA_IN ')
    line = line.replace(' LASTA P@ ', ' LASTA_P@ ')
    line = line.replace(' LASTA UR ', ' LASTA_UR ')
    line = line.replace(' LATA SIG ', ' LATA_SIG ')
    line = line.replace(' LEASA UT ', ' LEASA_UT ')
    line = line.replace(' LEDA BORT ', ' LEDA_BORT ')
    line = line.replace(' LEDA IN ', ' LEDA_IN ')
    line = line.replace(' LEDA UT ', ' LEDA_UT ')
    line = line.replace(' LEGITIMERA SIG ', ' LEGITIMERA_SIG ')
    line = line.replace(' LERA NED ', ' LERA_NED ')
    line = line.replace(' LETA FRAM ', ' LETA_FRAM ')
    line = line.replace(' LETA SIG FRAM ', ' LETA_SIG_FRAM ')
    line = line.replace(' LETA UPP ', ' LETA_UPP ')
    line = line.replace(' LEVA OM ', ' LEVA_OM ')
    line = line.replace(' LEVA SIG IN I ', ' LEVA_SIG_IN_I ')
    line = line.replace(' LEVA UPP ', ' LEVA_UPP ')
    line = line.replace(' LEVA UT ', ' LEVA_UT ')
    line = line.replace(' LEVRA SIG ', ' LEVRA_SIG ')
    line = line.replace(' LIERA SIG ', ' LIERA_SIG ')
    line = line.replace(' LIGGA AN ', ' LIGGA_AN ')
    line = line.replace(' LIGGA I ', ' LIGGA_I ')
    line = line.replace(' LIGGA KVAR ', ' LIGGA_KVAR ')
    line = line.replace(' LIGGA TILL SIG ', ' LIGGA_TILL_SIG ')
    line = line.replace(' LIMMA IHOP ', ' LIMMA_IHOP ')
    line = line.replace(' LINDA IN ', ' LINDA_IN ')
    line = line.replace(' LINJERA UPP ', ' LINJERA_UPP ')
    line = line.replace(' LIRKA UPP ', ' LIRKA_UPP ')
    line = line.replace(' LISTA SIG TILL ', ' LISTA_SIG_TILL ')
    line = line.replace(' LISTA UT ', ' LISTA_UT ')
    line = line.replace(' LIVA UPP ', ' LIVA_UPP ')
    line = line.replace(' LJUGA BORT ', ' LJUGA_BORT ')
    line = line.replace(' LJUGA SIG FRI ', ' LJUGA_SIG_FRI ')
    line = line.replace(' LJUMMA UPP ', ' LJUMMA_UPP ')
    line = line.replace(' LOCKA AV ', ' LOCKA_AV ')
    line = line.replace(' LOCKA BORT ', ' LOCKA_BORT ')
    line = line.replace(' LOCKA FRAM ', ' LOCKA_FRAM ')
    line = line.replace(' LOCKA IN ', ' LOCKA_IN ')
    line = line.replace(' LOCKA TILL SIG ', ' LOCKA_TILL_SIG ')
    line = line.replace(' LOCKA UT ', ' LOCKA_UT ')
    line = line.replace(' LOGGA IN ', ' LOGGA_IN ')
    line = line.replace(' LOGGA UT ', ' LOGGA_UT ')
    line = line.replace(' LOMMA BORT ', ' LOMMA_BORT ')
    line = line.replace(' LOMMA IN ', ' LOMMA_IN ')
    line = line.replace(' LOMMA IV$G ', ' LOMMA_IV$G ')
    line = line.replace(' LOPPA SIG ', ' LOPPA_SIG ')
    line = line.replace(' LORTA NER ', ' LORTA_NER ')
    line = line.replace(' LOTTA UT ', ' LOTTA_UT ')
    line = line.replace(' LOVA BORT ', ' LOVA_BORT ')
    line = line.replace(' LUBBA IV$G ', ' LUBBA_IV$G ')
    line = line.replace(' LUCKRA UPP ', ' LUCKRA_UPP ')
    line = line.replace(' LUDDA SIG ', ' LUDDA_SIG ')
    line = line.replace(' LUGNA NED ', ' LUGNA_NED ')
    line = line.replace(' LUGNA SIG ', ' LUGNA_SIG ')
    line = line.replace(' LUKTA BR$NT ', ' LUKTA_BR$NT ')
    line = line.replace(' LUKTA ILLA ', ' LUKTA_ILLA ')
    line = line.replace(' LUNKA IV$G ', ' LUNKA_IV$G ')
    line = line.replace(' LUNKA P@ ', ' LUNKA_P@ ')
    line = line.replace(' LURA AV ', ' LURA_AV ')
    line = line.replace(' LURA BORT ', ' LURA_BORT ')
    line = line.replace(' LURA UT ', ' LURA_UT ')
    line = line.replace(' LUSA NER ', ' LUSA_NER ')
    line = line.replace(' LUSKA UT ', ' LUSKA_UT ')
    line = line.replace(' LUTA SIG ', ' LUTA_SIG ')
    line = line.replace(' LYCK#NSKA SIG ', ' LYCK#NSKA_SIG ')
    line = line.replace(' LYCKA TILL ', ' LYCKA_TILL ')
    line = line.replace(' LYFTA AV ', ' LYFTA_AV ')
    line = line.replace(' LYFTA FRAM ', ' LYFTA_FRAM ')
    line = line.replace(' LYFTA UPP ', ' LYFTA_UPP ')
    line = line.replace(' LYFTA UT ', ' LYFTA_UT ')
    line = line.replace(' LYSA AV ', ' LYSA_AV ')
    line = line.replace(' LYSA UPP ', ' LYSA_UPP ')
    line = line.replace(' M@LA AV ', ' M@LA_AV ')
    line = line.replace(' M@LA OM ', ' M@LA_OM ')
    line = line.replace(' M@LA UPP ', ' M@LA_UPP ')
    line = line.replace(' M@TTA IN ', ' M@TTA_IN ')
    line = line.replace(' M#BLERA OM ', ' M#BLERA_OM ')
    line = line.replace(' M#DA SIG ', ' M#DA_SIG ')
    line = line.replace(' M#NSTRA AV ', ' M#NSTRA_AV ')
    line = line.replace(' M#NSTRA P@ ', ' M#NSTRA_P@ ')
    line = line.replace(' M#NSTRA UT ', ' M#NSTRA_UT ')
    line = line.replace(' M#TA UPP ', ' M#TA_UPP ')
    line = line.replace(' M$KLA FRED ', ' M$KLA_FRED ')
    line = line.replace(' M$KTA MED ', ' M$KTA_MED ')
    line = line.replace(' M$RKA AV ', ' M$RKA_AV ')
    line = line.replace(' M$RKA UPP ', ' M$RKA_UPP ')
    line = line.replace(' M$RKA UT ', ' M$RKA_UT ')
    line = line.replace(' M$TA AV ', ' M$TA_AV ')
    line = line.replace(' M$TA SIG ', ' M$TA_SIG ')
    line = line.replace(' M$TA UPP ', ' M$TA_UPP ')
    line = line.replace(' M$TA UT ', ' M$TA_UT ')
    line = line.replace(' MAKA IHOP SIG ', ' MAKA_IHOP_SIG ')
    line = line.replace(' MAKA SIG ', ' MAKA_SIG ')
    line = line.replace(' MALA IN ', ' MALA_IN ')
    line = line.replace(' MALLA SIG ', ' MALLA_SIG ')
    line = line.replace(' MANA FRAM ', ' MANA_FRAM ')
    line = line.replace(' MANA IN ', ' MANA_IN ')
    line = line.replace(' MANA P@ ', ' MANA_P@ ')
    line = line.replace(' MANGLA UT ', ' MANGLA_UT ')
    line = line.replace(' MASA SIG ', ' MASA_SIG ')
    line = line.replace(' MASKA P@ ', ' MASKA_P@ ')
    line = line.replace(' MASKERA SIG ', ' MASKERA_SIG ')
    line = line.replace(' MATA FRAM ', ' MATA_FRAM ')
    line = line.replace(' MATA IN ', ' MATA_IN ')
    line = line.replace(' MATA UT ', ' MATA_UT ')
    line = line.replace(' MATTAS UT ', ' MATTAS_UT ')
    line = line.replace(' MED FLERA ', ' MED_FLERA ')
    line = line.replace(' MED KAND ', ' MED_KAND ')
    line = line.replace(' MEJA NED ', ' MEJA_NED ')
    line = line.replace(' MEJSLA UT ', ' MEJSLA_UT ')
    line = line.replace(' MERITERA SIG ', ' MERITERA_SIG ')
    line = line.replace(' META UPP ', ' META_UPP ')
    line = line.replace(' MINSKA NED ', ' MINSKA_NED ')
    line = line.replace(' MISS$GA SIG ', ' MISS$GA_SIG ')
    line = line.replace(' MISSK#TA SIG ', ' MISSK#TA_SIG ')
    line = line.replace(' MISSMINNA SIG ', ' MISSMINNA_SIG ')
    line = line.replace(' MISSR$KNA SIG ', ' MISSR$KNA_SIG ')
    line = line.replace(' MISSTA SIG ', ' MISSTA_SIG ')
    line = line.replace(' MISSTAGA SIG ', ' MISSTAGA_SIG ')
    line = line.replace(' MJ#LA IN ', ' MJ#LA_IN ')
    line = line.replace(' MJ#LKA UT ', ' MJ#LKA_UT ')
    line = line.replace(' MJUKA UPP ', ' MJUKA_UPP ')
    line = line.replace(' MOJA SIG ', ' MOJA_SIG ')
    line = line.replace(' MONTERA IN ', ' MONTERA_IN ')
    line = line.replace(' MONTERA NED ', ' MONTERA_NED ')
    line = line.replace(' MONTERA UPP ', ' MONTERA_UPP ')
    line = line.replace(' MOPSA SIG ', ' MOPSA_SIG ')
    line = line.replace(' MOPSA UPP SIG ', ' MOPSA_UPP_SIG ')
    line = line.replace(' MORNA SIG ', ' MORNA_SIG ')
    line = line.replace(' MORSKA UPP SIG ', ' MORSKA_UPP_SIG ')
    line = line.replace(' MORSKNA TILL ', ' MORSKNA_TILL ')
    line = line.replace(' MOTA BORT ', ' MOTA_BORT ')
    line = line.replace(' MOTS$TTA SIG ', ' MOTS$TTA_SIG ')
    line = line.replace(' MULA IN ', ' MULA_IN ')
    line = line.replace(' MULNA IGEN ', ' MULNA_IGEN ')
    line = line.replace(' MULNA P@ ', ' MULNA_P@ ')
    line = line.replace(' MULTIPLICERA SIG ', ' MULTIPLICERA_SIG ')
    line = line.replace(' MULTNA BORT ', ' MULTNA_BORT ')
    line = line.replace(' MUMSA I SIG ', ' MUMSA_I_SIG ')
    line = line.replace(' MUNTRA UPP ', ' MUNTRA_UPP ')
    line = line.replace(' MURA IGEN ', ' MURA_IGEN ')
    line = line.replace(' MURA IN ', ' MURA_IN ')
    line = line.replace(' MUTA IN ', ' MUTA_IN ')
    line = line.replace(' MYLLA NED ', ' MYLLA_NED ')
    line = line.replace(' MYNNA UT ', ' MYNNA_UT ')
    line = line.replace(' N@ FRAM ', ' N@_FRAM ')
    line = line.replace(' N@ UT ', ' N@_UT ')
    line = line.replace(' N@LA FAST ', ' N@LA_FAST ')
    line = line.replace(' N@LA UPP ', ' N@LA_UPP ')
    line = line.replace(' N#JA SIG ', ' N#JA_SIG ')
    line = line.replace(' N#TA AV ', ' N#TA_AV ')
    line = line.replace(' N#TA BORT ', ' N#TA_BORT ')
    line = line.replace(' N#TA IN ', ' N#TA_IN ')
    line = line.replace(' N#TA NED ', ' N#TA_NED ')
    line = line.replace(' N#TA UT ', ' N#TA_UT ')
    line = line.replace(' N$RA SIG ', ' N$RA_SIG ')
    line = line.replace(' N$RMA SIG ', ' N$RMA_SIG ')
    line = line.replace(' N$STLA IN ', ' N$STLA_IN ')
    line = line.replace(' N$STLA SIG IN ', ' N$STLA_SIG_IN ')
    line = line.replace(' NAGLA FAST ', ' NAGLA_FAST ')
    line = line.replace(' NAPPA @T SIG ', ' NAPPA_@T_SIG ')
    line = line.replace(' NAPPA TAG ', ' NAPPA_TAG ')
    line = line.replace(' NAPPA TILL SIG ', ' NAPPA_TILL_SIG ')
    line = line.replace(' NEDL@TA SIG ', ' NEDL@TA_SIG ')
    line = line.replace(' NEKA SIG ', ' NEKA_SIG ')
    line = line.replace(' NICKA IN ', ' NICKA_IN ')
    line = line.replace(' NICKA TILL ', ' NICKA_TILL ')
    line = line.replace(' NITA FAST ', ' NITA_FAST ')
    line = line.replace(' NITA TILL ', ' NITA_TILL ')
    line = line.replace(' NOSA UPP ', ' NOSA_UPP ')
    line = line.replace(' NYKTRA TILL ', ' NYKTRA_TILL ')
    line = line.replace(' NYPA @T ', ' NYPA_@T ')
    line = line.replace(' NYPA AV ', ' NYPA_AV ')
    line = line.replace(' NYPA TILL ', ' NYPA_TILL ')
    line = line.replace(' NYSA TILL ', ' NYSA_TILL ')
    line = line.replace(' NYSTA AV ', ' NYSTA_AV ')
    line = line.replace(' NYSTA UPP ', ' NYSTA_UPP ')
    line = line.replace(' OCH S@ VIDARE ', ' OCH_S@_VIDARE ')
    line = line.replace(' ODLA UPP ', ' ODLA_UPP ')
    line = line.replace(' OFFRA SIG ', ' OFFRA_SIG ')
    line = line.replace(' OJA SIG ', ' OJA_SIG ')
    line = line.replace(' OLJA IN ', ' OLJA_IN ')
    line = line.replace(' OMAKA SIG ', ' OMAKA_SIG ')
    line = line.replace(' ONDG#RA SIG ', ' ONDG#RA_SIG ')
    line = line.replace(' OPERERA IN ', ' OPERERA_IN ')
    line = line.replace(' ORDNA IN ', ' ORDNA_IN ')
    line = line.replace(' ORDNA SIG ', ' ORDNA_SIG ')
    line = line.replace(' ORDNA UPP ', ' ORDNA_UPP ')
    line = line.replace(' ORGANISERA SIG ', ' ORGANISERA_SIG ')
    line = line.replace(' ORIENTERA SIG ', ' ORIENTERA_SIG ')
    line = line.replace(' ORKA MED ', ' ORKA_MED ')
    line = line.replace(' ORMA SIG ', ' ORMA_SIG ')
    line = line.replace(' OSTA SIG ', ' OSTA_SIG ')
    line = line.replace(' P@ GRUND AV ', ' P@_GRUND_AV ')
    line = line.replace(' P$LSA AV ', ' P$LSA_AV ')
    line = line.replace(' P$LSA P@ ', ' P$LSA_P@ ')
    line = line.replace(' P$LSA P@ SIG ', ' P$LSA_P@_SIG ')
    line = line.replace(' PACKA IHOP ', ' PACKA_IHOP ')
    line = line.replace(' PACKA IN ', ' PACKA_IN ')
    line = line.replace(' PACKA NER ', ' PACKA_NER ')
    line = line.replace(' PACKA SIG ', ' PACKA_SIG ')
    line = line.replace(' PACKA UPP ', ' PACKA_UPP ')
    line = line.replace(' PALLA UPP ', ' PALLA_UPP ')
    line = line.replace(' PALLRA SIG ', ' PALLRA_SIG ')
    line = line.replace(' PALLRA SIG IV$G ', ' PALLRA_SIG_IV$G ')
    line = line.replace(' PALTA P@ ', ' PALTA_P@ ')
    line = line.replace(' PARA SIG ', ' PARA_SIG ')
    line = line.replace(' PASSA IN ', ' PASSA_IN ')
    line = line.replace(' PASSA P@ ', ' PASSA_P@ ')
    line = line.replace(' PASSA SIG ', ' PASSA_SIG ')
    line = line.replace(' PASSA UPP ', ' PASSA_UPP ')
    line = line.replace(' PASSERA IN ', ' PASSERA_IN ')
    line = line.replace(' PASSERA UT ', ' PASSERA_UT ')
    line = line.replace(' PEJLA IN ', ' PEJLA_IN ')
    line = line.replace(' PEKA UT ', ' PEKA_UT ')
    line = line.replace(' PEPPA UPP ', ' PEPPA_UPP ')
    line = line.replace(' PETA IN ', ' PETA_IN ')
    line = line.replace(' PIGGA UPP ', ' PIGGA_UPP ')
    line = line.replace(' PIGGNA TILL ', ' PIGGNA_TILL ')
    line = line.replace(' PILA IV$G ', ' PILA_IV$G ')
    line = line.replace(' PINNA P@ ', ' PINNA_P@ ')
    line = line.replace(' PISKA UPP ', ' PISKA_UPP ')
    line = line.replace(' PL@STRA OM ', ' PL@STRA_OM ')
    line = line.replace(' PL#JA NED ', ' PL#JA_NED ')
    line = line.replace(' PL#JA UPP ', ' PL#JA_UPP ')
    line = line.replace(' PLACERA IN ', ' PLACERA_IN ')
    line = line.replace(' PLACERA UT ', ' PLACERA_UT ')
    line = line.replace(' PLANA UT ', ' PLANA_UT ')
    line = line.replace(' PLANERA IN ', ' PLANERA_IN ')
    line = line.replace(' PLANTERA IN ', ' PLANTERA_IN ')
    line = line.replace(' PLASTA IN ', ' PLASTA_IN ')
    line = line.replace(' PLATTA TILL ', ' PLATTA_TILL ')
    line = line.replace(' PLOCKA AV ', ' PLOCKA_AV ')
    line = line.replace(' PLOCKA BORT ', ' PLOCKA_BORT ')
    line = line.replace(' PLOCKA FRAM ', ' PLOCKA_FRAM ')
    line = line.replace(' PLOCKA IN ', ' PLOCKA_IN ')
    line = line.replace(' PLOCKA IS$R ', ' PLOCKA_IS$R ')
    line = line.replace(' PLOCKA NED ', ' PLOCKA_NED ')
    line = line.replace(' PLOCKA UPP ', ' PLOCKA_UPP ')
    line = line.replace(' PLOCKA UT ', ' PLOCKA_UT ')
    line = line.replace(' PLOTTRA BORT ', ' PLOTTRA_BORT ')
    line = line.replace(' PLUGGA IGEN ', ' PLUGGA_IGEN ')
    line = line.replace(' PLUMSA I ', ' PLUMSA_I ')
    line = line.replace(' PLUSSA P@ ', ' PLUSSA_P@ ')
    line = line.replace(' POLERA UPP ', ' POLERA_UPP ')
    line = line.replace(' POSTE RESTANTE ', ' POSTE_RESTANTE ')
    line = line.replace(' PR@NGLA UT ', ' PR@NGLA_UT ')
    line = line.replace(' PR#VA P@ ', ' PR#VA_P@ ')
    line = line.replace(' PR$GLA IN ', ' PR$GLA_IN ')
    line = line.replace(' PR$NTA IN ', ' PR$NTA_IN ')
    line = line.replace(' PRACKA P@ ', ' PRACKA_P@ ')
    line = line.replace(' PRESENTERA SIG ', ' PRESENTERA_SIG ')
    line = line.replace(' PRESSA IN ', ' PRESSA_IN ')
    line = line.replace(' PRESSA UT ', ' PRESSA_UT ')
    line = line.replace(' PRICKA AV ', ' PRICKA_AV ')
    line = line.replace(' PRICKA IN ', ' PRICKA_IN ')
    line = line.replace(' PROFILERA SIG ', ' PROFILERA_SIG ')
    line = line.replace(' PROGRAMMERA IN ', ' PROGRAMMERA_IN ')
    line = line.replace(' PROVA P@ ', ' PROVA_P@ ')
    line = line.replace(' PUCKLA P@ ', ' PUCKLA_P@ ')
    line = line.replace(' PUFFA TILL ', ' PUFFA_TILL ')
    line = line.replace(' PUFFA UPP ', ' PUFFA_UPP ')
    line = line.replace(' PUMPA I ', ' PUMPA_I ')
    line = line.replace(' PUMPA L$NS ', ' PUMPA_L$NS ')
    line = line.replace(' PUMPA UPP ', ' PUMPA_UPP ')
    line = line.replace(' PUNGA UT ', ' PUNGA_UT ')
    line = line.replace(' PUNKTERA UT ', ' PUNKTERA_UT ')
    line = line.replace(' PUSTA UT ', ' PUSTA_UT ')
    line = line.replace(' PUTA FRAM ', ' PUTA_FRAM ')
    line = line.replace(' PUTA UT ', ' PUTA_UT ')
    line = line.replace(' PUTSA AV ', ' PUTSA_AV ')
    line = line.replace(' PUTTA NED ', ' PUTTA_NED ')
    line = line.replace(' PUTTA NER ', ' PUTTA_NER ')
    line = line.replace(' PYSA #VER ', ' PYSA_#VER ')
    line = line.replace(' R#DA KORS ', ' R#DA_KORS ')
    line = line.replace(' R#DA KORS ', ' R#DA_KORS ')
    line = line.replace(' R#DA KORSET ', ' R#DA_KORSET ')
    line = line.replace(' R#DA KORSETS ', ' R#DA_KORSETS ')
    line = line.replace(' R#JA AV ', ' R#JA_AV ')
    line = line.replace(' R#JA SIG ', ' R#JA_SIG ')
    line = line.replace(' R#JA UPP ', ' R#JA_UPP ')
    line = line.replace(' R#KA IN ', ' R#KA_IN ')
    line = line.replace(' R#RA SIG ', ' R#RA_SIG ')
    line = line.replace(' R#SA AV ', ' R#SA_AV ')
    line = line.replace(' R$CKA UT ', ' R$CKA_UT ')
    line = line.replace(' R$DDA SIG ', ' R$DDA_SIG ')
    line = line.replace(' R$KNA AV ', ' R$KNA_AV ')
    line = line.replace(' R$KNA IN ', ' R$KNA_IN ')
    line = line.replace(' R$KNA NED ', ' R$KNA_NED ')
    line = line.replace(' R$KNA UPP ', ' R$KNA_UPP ')
    line = line.replace(' R$KNA UT ', ' R$KNA_UT ')
    line = line.replace(' R$NTA SIG ', ' R$NTA_SIG ')
    line = line.replace(' R$TA UT ', ' R$TA_UT ')
    line = line.replace(' R$TTA SIG ', ' R$TTA_SIG ')
    line = line.replace(' R$TTA TILL ', ' R$TTA_TILL ')
    line = line.replace(' RABBLA UPP ', ' RABBLA_UPP ')
    line = line.replace(' RACKA NER ', ' RACKA_NER ')
    line = line.replace(' RACKA NER P@ ', ' RACKA_NER_P@ ')
    line = line.replace(' RADA UPP ', ' RADA_UPP ')
    line = line.replace(' RADERA UT ', ' RADERA_UT ')
    line = line.replace(' RAFSA @T SIG ', ' RAFSA_@T_SIG ')
    line = line.replace(' RAFSA IHOP ', ' RAFSA_IHOP ')
    line = line.replace(' RAGGA UPP ', ' RAGGA_UPP ')
    line = line.replace(' RAKA AV ', ' RAKA_AV ')
    line = line.replace(' RAKA IHOP ', ' RAKA_IHOP ')
    line = line.replace(' RAMA IN ', ' RAMA_IN ')
    line = line.replace(' RAMLA AV ', ' RAMLA_AV ')
    line = line.replace(' RAMLA IN ', ' RAMLA_IN ')
    line = line.replace(' RAMLA NER ', ' RAMLA_NER ')
    line = line.replace(' RAMLA OMKULL ', ' RAMLA_OMKULL ')
    line = line.replace(' RAMLA UR ', ' RAMLA_UR ')
    line = line.replace(' RAMLA UT ', ' RAMLA_UT ')
    line = line.replace(' RANTA OMKRING ', ' RANTA_OMKRING ')
    line = line.replace(' RAPPA @T SIG ', ' RAPPA_@T_SIG ')
    line = line.replace(' RAPPA SIG ', ' RAPPA_SIG ')
    line = line.replace(' RAPPA TILL ', ' RAPPA_TILL ')
    line = line.replace(' RAPPORTERA IN ', ' RAPPORTERA_IN ')
    line = line.replace(' RASKA P@ ', ' RASKA_P@ ')
    line = line.replace(' REDA AV ', ' REDA_AV ')
    line = line.replace(' REDA SIG ', ' REDA_SIG ')
    line = line.replace(' REDA UPP ', ' REDA_UPP ')
    line = line.replace(' REDA UT ', ' REDA_UT ')
    line = line.replace(' REGISTRERA IN ', ' REGISTRERA_IN ')
    line = line.replace(' REKREERA SIG ', ' REKREERA_SIG ')
    line = line.replace(' RENSA UPP ', ' RENSA_UPP ')
    line = line.replace(' REPA AV ', ' REPA_AV ')
    line = line.replace(' REPA SIG ', ' REPA_SIG ')
    line = line.replace(' REPA UPP ', ' REPA_UPP ')
    line = line.replace(' RESA BORT ', ' RESA_BORT ')
    line = line.replace(' RESA IN ', ' RESA_IN ')
    line = line.replace(' RESA SIG ', ' RESA_SIG ')
    line = line.replace(' RESA UPP ', ' RESA_UPP ')
    line = line.replace(' RESA UT ', ' RESA_UT ')
    line = line.replace(' RESERVERA SIG ', ' RESERVERA_SIG ')
    line = line.replace(' RETA SIG ', ' RETA_SIG ')
    line = line.replace(' RETA UPP ', ' RETA_UPP ')
    line = line.replace(' REVANSCHERA SIG ', ' REVANSCHERA_SIG ')
    line = line.replace(' RIDA AV ', ' RIDA_AV ')
    line = line.replace(' RIDA IN ', ' RIDA_IN ')
    line = line.replace(' RIGGA AV ', ' RIGGA_AV ')
    line = line.replace(' RIGGA UPP ', ' RIGGA_UPP ')
    line = line.replace(' RIKTA IN ', ' RIKTA_IN ')
    line = line.replace(' RIKTA SIG ', ' RIKTA_SIG ')
    line = line.replace(' RINGA AV ', ' RINGA_AV ')
    line = line.replace(' RINGA IN ', ' RINGA_IN ')
    line = line.replace(' RINGA UPP ', ' RINGA_UPP ')
    line = line.replace(' RINGLA SIG ', ' RINGLA_SIG ')
    line = line.replace(' RINNA #VER ', ' RINNA_#VER ')
    line = line.replace(' RINNA AV ', ' RINNA_AV ')
    line = line.replace(' RINNA IV$G ', ' RINNA_IV$G ')
    line = line.replace(' RINNA UPP ', ' RINNA_UPP ')
    line = line.replace(' RISPA AV ', ' RISPA_AV ')
    line = line.replace(' RISPA UPP ', ' RISPA_UPP ')
    line = line.replace(' RISTA IN ', ' RISTA_IN ')
    line = line.replace(' RITA AV ', ' RITA_AV ')
    line = line.replace(' RITA UPP ', ' RITA_UPP ')
    line = line.replace(' RIVA @T SIG ', ' RIVA_@T_SIG ')
    line = line.replace(' RIVA AV ', ' RIVA_AV ')
    line = line.replace(' RIVA I ', ' RIVA_I ')
    line = line.replace(' RIVA ITU ', ' RIVA_ITU ')
    line = line.replace(' RIVA L#S ', ' RIVA_L#S ')
    line = line.replace(' RIVA LOSS ', ' RIVA_LOSS ')
    line = line.replace(' RO HIT ', ' RO_HIT ')
    line = line.replace(' ROA SIG ', ' ROA_SIG ')
    line = line.replace(' ROFFA @T SIG ', ' ROFFA_@T_SIG ')
    line = line.replace(' ROPA AN ', ' ROPA_AN ')
    line = line.replace(' ROPA IN ', ' ROPA_IN ')
    line = line.replace(' ROPA UPP ', ' ROPA_UPP ')
    line = line.replace(' ROPA UT ', ' ROPA_UT ')
    line = line.replace(' ROTA SIG ', ' ROTA_SIG ')
    line = line.replace(' RUGGA UPP ', ' RUGGA_UPP ')
    line = line.replace(' RULLA AV ', ' RULLA_AV ')
    line = line.replace(' RULLA IN ', ' RULLA_IN ')
    line = line.replace(' RULLA NER ', ' RULLA_NER ')
    line = line.replace(' RULLA SIG ', ' RULLA_SIG ')
    line = line.replace(' RULLA UPP ', ' RULLA_UPP ')
    line = line.replace(' RULLA UT ', ' RULLA_UT ')
    line = line.replace(' RUMLA OM ', ' RUMLA_OM ')
    line = line.replace(' RUMSTERA OM ', ' RUMSTERA_OM ')
    line = line.replace(' RUNDA AV ', ' RUNDA_AV ')
    line = line.replace(' RUNDA TILL ', ' RUNDA_TILL ')
    line = line.replace(' RUSA IN ', ' RUSA_IN ')
    line = line.replace(' RUSA OMKRING ', ' RUSA_OMKRING ')
    line = line.replace(' RUSKA AV ', ' RUSKA_AV ')
    line = line.replace(' RUSTA SIG ', ' RUSTA_SIG ')
    line = line.replace(' RUSTA UPP ', ' RUSTA_UPP ')
    line = line.replace(' RUTA IN ', ' RUTA_IN ')
    line = line.replace(' RUTER @TTA ', ' RUTER_@TTA ')
    line = line.replace(' RUTER @TTAN ', ' RUTER_@TTAN ')
    line = line.replace(' RUTER @TTANS ', ' RUTER_@TTANS ')
    line = line.replace(' RUTER @TTAS ', ' RUTER_@TTAS ')
    line = line.replace(' RUTER @TTOR ', ' RUTER_@TTOR ')
    line = line.replace(' RUTER @TTORNA ', ' RUTER_@TTORNA ')
    line = line.replace(' RUTER @TTORNAS ', ' RUTER_@TTORNAS ')
    line = line.replace(' RUTER @TTORS ', ' RUTER_@TTORS ')
    line = line.replace(' RUTER ESS ', ' RUTER_ESS ')
    line = line.replace(' RUTER ESS ', ' RUTER_ESS ')
    line = line.replace(' RUTER ESS ', ' RUTER_ESS ')
    line = line.replace(' RUTER ESS ', ' RUTER_ESS ')
    line = line.replace(' RUTER ESS ', ' RUTER_ESS ')
    line = line.replace(' RUTER ESSEN ', ' RUTER_ESSEN ')
    line = line.replace(' RUTER ESSENS ', ' RUTER_ESSENS ')
    line = line.replace(' RUTER ESSET ', ' RUTER_ESSET ')
    line = line.replace(' RUTER ESSETS ', ' RUTER_ESSETS ')
    line = line.replace(' RUTER FYRA ', ' RUTER_FYRA ')
    line = line.replace(' RUTER FYRAN ', ' RUTER_FYRAN ')
    line = line.replace(' RUTER FYRANS ', ' RUTER_FYRANS ')
    line = line.replace(' RUTER FYRAS ', ' RUTER_FYRAS ')
    line = line.replace(' RUTER FYROR ', ' RUTER_FYROR ')
    line = line.replace(' RUTER FYRORNA ', ' RUTER_FYRORNA ')
    line = line.replace(' RUTER FYRORNAS ', ' RUTER_FYRORNAS ')
    line = line.replace(' RUTER FYRORS ', ' RUTER_FYRORS ')
    line = line.replace(' RUTER KNEKT ', ' RUTER_KNEKT ')
    line = line.replace(' RUTER KNEKTAR ', ' RUTER_KNEKTAR ')
    line = line.replace(' RUTER KNEKTARNA ', ' RUTER_KNEKTARNA ')
    line = line.replace(' RUTER KNEKTARNAS ', ' RUTER_KNEKTARNAS ')
    line = line.replace(' RUTER KNEKTARS ', ' RUTER_KNEKTARS ')
    line = line.replace(' RUTER KNEKTEN ', ' RUTER_KNEKTEN ')
    line = line.replace(' RUTER KNEKTENS ', ' RUTER_KNEKTENS ')
    line = line.replace(' RUTER KNEKTS ', ' RUTER_KNEKTS ')
    line = line.replace(' RUTER TRE ', ' RUTER_TRE ')
    line = line.replace(' RYCKA IN ', ' RYCKA_IN ')
    line = line.replace(' RYCKA LOSS ', ' RYCKA_LOSS ')
    line = line.replace(' RYCKA UPP ', ' RYCKA_UPP ')
    line = line.replace(' RYKA IN ', ' RYKA_IN ')
    line = line.replace(' RYNKA SIG ', ' RYNKA_SIG ')
    line = line.replace(' S@ KALLAD ', ' S@_KALLAD ')
    line = line.replace(' S@ UT ', ' S@_UT ')
    line = line.replace(' S@GA AV ', ' S@GA_AV ')
    line = line.replace(' S@GA UPP ', ' S@GA_UPP ')
    line = line.replace(' S@LLA BORT ', ' S@LLA_BORT ')
    line = line.replace(' S#KA AV ', ' S#KA_AV ')
    line = line.replace(' S#KA SIG ', ' S#KA_SIG ')
    line = line.replace(' S#KA UPP ', ' S#KA_UPP ')
    line = line.replace(' S#KA UT ', ' S#KA_UT ')
    line = line.replace(' S#LA NER ', ' S#LA_NER ')
    line = line.replace(' S#RJA F#R ', ' S#RJA_F#R ')
    line = line.replace(' S#RPLA I SIG ', ' S#RPLA_I_SIG ')
    line = line.replace(' S#VA NED ', ' S#VA_NED ')
    line = line.replace(' S$CKA EFTER ', ' S$CKA_EFTER ')
    line = line.replace(' S$GA EFTER ', ' S$GA_EFTER ')
    line = line.replace(' S$GA EMOT ', ' S$GA_EMOT ')
    line = line.replace(' S$GA IFR@N ', ' S$GA_IFR@N ')
    line = line.replace(' S$GA TILL ', ' S$GA_TILL ')
    line = line.replace(' S$GA UPP ', ' S$GA_UPP ')
    line = line.replace(' S$LJA AV ', ' S$LJA_AV ')
    line = line.replace(' S$LJA UT ', ' S$LJA_UT ')
    line = line.replace(' S$LLA SIG ', ' S$LLA_SIG ')
    line = line.replace(' S$NDA AV ', ' S$NDA_AV ')
    line = line.replace(' S$NDA BORT ', ' S$NDA_BORT ')
    line = line.replace(' S$NDA IN ', ' S$NDA_IN ')
    line = line.replace(' S$NDA UT ', ' S$NDA_UT ')
    line = line.replace(' S$NKA NED ', ' S$NKA_NED ')
    line = line.replace(' S$TTA @T ', ' S$TTA_@T ')
    line = line.replace(' S$TTA #VER ', ' S$TTA_#VER ')
    line = line.replace(' S$TTA AV ', ' S$TTA_AV ')
    line = line.replace(' S$TTA EFTER ', ' S$TTA_EFTER ')
    line = line.replace(' S$TTA F#R ', ' S$TTA_F#R ')
    line = line.replace(' S$TTA FRAM ', ' S$TTA_FRAM ')
    line = line.replace(' S$TTA I ', ' S$TTA_I ')
    line = line.replace(' S$TTA I SIG ', ' S$TTA_I_SIG ')
    line = line.replace(' S$TTA IG@NG ', ' S$TTA_IG@NG ')
    line = line.replace(' S$TTA IGEN ', ' S$TTA_IGEN ')
    line = line.replace(' S$TTA IHOP ', ' S$TTA_IHOP ')
    line = line.replace(' S$TTA IN ', ' S$TTA_IN ')
    line = line.replace(' S$TTA NER ', ' S$TTA_NER ')
    line = line.replace(' S$TTA P@ ', ' S$TTA_P@ ')
    line = line.replace(' S$TTA P@ SIG ', ' S$TTA_P@_SIG ')
    line = line.replace(' S$TTA SIG ', ' S$TTA_SIG ')
    line = line.replace(' S$TTA UNDAN ', ' S$TTA_UNDAN ')
    line = line.replace(' S$TTA UPP ', ' S$TTA_UPP ')
    line = line.replace(' S$TTA UT ', ' S$TTA_UT ')
    line = line.replace(' SABLA NED ', ' SABLA_NED ')
    line = line.replace(' SACKA AV ', ' SACKA_AV ')
    line = line.replace(' SADLA OM ', ' SADLA_OM ')
    line = line.replace(' SAKTA AV ', ' SAKTA_AV ')
    line = line.replace(' SAKTA IN ', ' SAKTA_IN ')
    line = line.replace(' SAKTA NED ', ' SAKTA_NED ')
    line = line.replace(' SAKTA UPP ', ' SAKTA_UPP ')
    line = line.replace(' SALTA IN ', ' SALTA_IN ')
    line = line.replace(' SAMLA IHOP ', ' SAMLA_IHOP ')
    line = line.replace(' SAMLA IN ', ' SAMLA_IN ')
    line = line.replace(' SAMLA SIG ', ' SAMLA_SIG ')
    line = line.replace(' SAMLA UPP ', ' SAMLA_UPP ')
    line = line.replace(' SANSA SIG ', ' SANSA_SIG ')
    line = line.replace(' SCHAKTA AV ', ' SCHAKTA_AV ')
    line = line.replace(' SCHAKTA BORT ', ' SCHAKTA_BORT ')
    line = line.replace(' SCHAKTA UR ', ' SCHAKTA_UR ')
    line = line.replace(' SCHAKTA UT ', ' SCHAKTA_UT ')
    line = line.replace(' SCHASA BORT ', ' SCHASA_BORT ')
    line = line.replace(' SCIENCE FICTION ', ' SCIENCE_FICTION ')
    line = line.replace(' SE #VER ', ' SE_#VER ')
    line = line.replace(' SE AV ', ' SE_AV ')
    line = line.replace(' SE BORT IFR@N ', ' SE_BORT_IFR@N ')
    line = line.replace(' SE EFTER ', ' SE_EFTER ')
    line = line.replace(' SE FRAM EMOT ', ' SE_FRAM_EMOT ')
    line = line.replace(' SE NER P@ ', ' SE_NER_P@ ')
    line = line.replace(' SE P@ ', ' SE_P@ ')
    line = line.replace(' SE SIG F#R ', ' SE_SIG_F#R ')
    line = line.replace(' SE SIG OM ', ' SE_SIG_OM ')
    line = line.replace(' SE TILL ', ' SE_TILL ')
    line = line.replace(' SE TILLBAKA ', ' SE_TILLBAKA ')
    line = line.replace(' SE UPP ', ' SE_UPP ')
    line = line.replace(' SEGA SIG ', ' SEGA_SIG ')
    line = line.replace(' SEGLA AV ', ' SEGLA_AV ')
    line = line.replace(' SEGLA IN ', ' SEGLA_IN ')
    line = line.replace(' SEGLA UT ', ' SEGLA_UT ')
    line = line.replace(' SEGNA NED ', ' SEGNA_NED ')
    line = line.replace(' SELA AV ', ' SELA_AV ')
    line = line.replace(' SENS MORAL ', ' SENS_MORAL ')
    line = line.replace(' SIGNA NED ', ' SIGNA_NED ')
    line = line.replace(' SILA AV ', ' SILA_AV ')
    line = line.replace(' SINA AV ', ' SINA_AV ')
    line = line.replace(' SINA UT ', ' SINA_UT ')
    line = line.replace(' SINTRA SIG ', ' SINTRA_SIG ')
    line = line.replace(' SIPPRA IN ', ' SIPPRA_IN ')
    line = line.replace(' SIPPRA UT ', ' SIPPRA_UT ')
    line = line.replace(' SITTA @T ', ' SITTA_@T ')
    line = line.replace(' SITTA AV ', ' SITTA_AV ')
    line = line.replace(' SITTA BORT ', ' SITTA_BORT ')
    line = line.replace(' SITTA EMELLAN ', ' SITTA_EMELLAN ')
    line = line.replace(' SITTA F#R ', ' SITTA_F#R ')
    line = line.replace(' SITTA FAST ', ' SITTA_FAST ')
    line = line.replace(' SITTA FRAM ', ' SITTA_FRAM ')
    line = line.replace(' SITTA I ', ' SITTA_I ')
    line = line.replace(' SITTA IGEN ', ' SITTA_IGEN ')
    line = line.replace(' SITTA IHOP ', ' SITTA_IHOP ')
    line = line.replace(' SITTA INNE ', ' SITTA_INNE ')
    line = line.replace(' SITTA KVAR ', ' SITTA_KVAR ')
    line = line.replace(' SITTA NER ', ' SITTA_NER ')
    line = line.replace(' SITTA P@ ', ' SITTA_P@ ')
    line = line.replace(' SITTA TILL ', ' SITTA_TILL ')
    line = line.replace(' SITTA UPP ', ' SITTA_UPP ')
    line = line.replace(' SITTA UPPE ', ' SITTA_UPPE ')
    line = line.replace(' SJ@PA SIG ', ' SJ@PA_SIG ')
    line = line.replace(' SJ$LVS@ SIG ', ' SJ$LVS@_SIG ')
    line = line.replace(' SJASKA NED ', ' SJASKA_NED ')
    line = line.replace(' SJUNGA AV ', ' SJUNGA_AV ')
    line = line.replace(' SJUNGA IN ', ' SJUNGA_IN ')
    line = line.replace(' SJUNGA UT ', ' SJUNGA_UT ')
    line = line.replace(' SJUNKA IHOP ', ' SJUNKA_IHOP ')
    line = line.replace(' SJUNKA IN ', ' SJUNKA_IN ')
    line = line.replace(' SJUNKA NED ', ' SJUNKA_NED ')
    line = line.replace(' SJUNKA NER ', ' SJUNKA_NER ')
    line = line.replace(' SJUNKA UNDAN ', ' SJUNKA_UNDAN ')
    line = line.replace(' SK@PA UT ', ' SK@PA_UT ')
    line = line.replace(' SK#LJA AV ', ' SK#LJA_AV ')
    line = line.replace(' SK#LJA BORT ', ' SK#LJA_BORT ')
    line = line.replace(' SK#RTA UPP ', ' SK#RTA_UPP ')
    line = line.replace(' SK#TA SIG ', ' SK#TA_SIG ')
    line = line.replace(' SK$LLA UT ', ' SK$LLA_UT ')
    line = line.replace(' SK$MMA BORT ', ' SK$MMA_BORT ')
    line = line.replace(' SK$NKA BORT ', ' SK$NKA_BORT ')
    line = line.replace(' SK$RA AV ', ' SK$RA_AV ')
    line = line.replace(' SK$RA BORT ', ' SK$RA_BORT ')
    line = line.replace(' SK$RA SIG ', ' SK$RA_SIG ')
    line = line.replace(' SK$RA UPP ', ' SK$RA_UPP ')
    line = line.replace(' SK$RMA AV ', ' SK$RMA_AV ')
    line = line.replace(' SK$RPA SIG ', ' SK$RPA_SIG ')
    line = line.replace(' SKAFFA FRAM ', ' SKAFFA_FRAM ')
    line = line.replace(' SKAFFA IN ', ' SKAFFA_IN ')
    line = line.replace(' SKAKA AV ', ' SKAKA_AV ')
    line = line.replace(' SKALA AV ', ' SKALA_AV ')
    line = line.replace(' SKALA BORT ', ' SKALA_BORT ')
    line = line.replace(' SKANSEN AKVARIET ', ' SKANSEN_AKVARIET ')
    line = line.replace(' SKARVA IHOP ', ' SKARVA_IHOP ')
    line = line.replace(' SKAVA AV ', ' SKAVA_AV ')
    line = line.replace(' SKENA IV$G ', ' SKENA_IV$G ')
    line = line.replace(' SKICKA IN ', ' SKICKA_IN ')
    line = line.replace(' SKICKA MED ', ' SKICKA_MED ')
    line = line.replace(' SKICKA SIG ', ' SKICKA_SIG ')
    line = line.replace(' SKICKA UT ', ' SKICKA_UT ')
    line = line.replace(' SKIFTA OM ', ' SKIFTA_OM ')
    line = line.replace(' SKIKTA SIG ', ' SKIKTA_SIG ')
    line = line.replace(' SKILJA AV ', ' SKILJA_AV ')
    line = line.replace(' SKILJA SIG ', ' SKILJA_SIG ')
    line = line.replace(' SKINA IN ', ' SKINA_IN ')
    line = line.replace(' SKINA UPP ', ' SKINA_UPP ')
    line = line.replace(' SKINGRA SIG ', ' SKINGRA_SIG ')
    line = line.replace(' SKITA NED ', ' SKITA_NED ')
    line = line.replace(' SKITA SIG ', ' SKITA_SIG ')
    line = line.replace(' SKIVA SIG ', ' SKIVA_SIG ')
    line = line.replace(' SKJUTA AV ', ' SKJUTA_AV ')
    line = line.replace(' SKJUTA IN ', ' SKJUTA_IN ')
    line = line.replace(' SKJUTA SIG ', ' SKJUTA_SIG ')
    line = line.replace(' SKJUTA UPP ', ' SKJUTA_UPP ')
    line = line.replace(' SKJUTA UT ', ' SKJUTA_UT ')
    line = line.replace(' SKO SIG ', ' SKO_SIG ')
    line = line.replace(' SKOCKA SIG ', ' SKOCKA_SIG ')
    line = line.replace(' SKOLA IN ', ' SKOLA_IN ')
    line = line.replace(' SKORPA SIG ', ' SKORPA_SIG ')
    line = line.replace(' SKOTA HEM ', ' SKOTA_HEM ')
    line = line.replace(' SKOTTA IGEN ', ' SKOTTA_IGEN ')
    line = line.replace(' SKR$MMA BORT ', ' SKR$MMA_BORT ')
    line = line.replace(' SKR$PA NED ', ' SKR$PA_NED ')
    line = line.replace(' SKRAPA AV ', ' SKRAPA_AV ')
    line = line.replace(' SKRATTA BORT ', ' SKRATTA_BORT ')
    line = line.replace(' SKRATTA TILL ', ' SKRATTA_TILL ')
    line = line.replace(' SKRATTA UT ', ' SKRATTA_UT ')
    line = line.replace(' SKRIDA IN ', ' SKRIDA_IN ')
    line = line.replace(' SKRIFTA SIG ', ' SKRIFTA_SIG ')
    line = line.replace(' SKRIKA TILL ', ' SKRIKA_TILL ')
    line = line.replace(' SKRIKA UT ', ' SKRIKA_UT ')
    line = line.replace(' SKRIVA AV ', ' SKRIVA_AV ')
    line = line.replace(' SKRIVA IN ', ' SKRIVA_IN ')
    line = line.replace(' SKRIVA NED ', ' SKRIVA_NED ')
    line = line.replace(' SKRIVA NER ', ' SKRIVA_NER ')
    line = line.replace(' SKRIVA OM ', ' SKRIVA_OM ')
    line = line.replace(' SKRIVA P@ ', ' SKRIVA_P@ ')
    line = line.replace(' SKRIVA UNDER ', ' SKRIVA_UNDER ')
    line = line.replace(' SKRIVA UPP ', ' SKRIVA_UPP ')
    line = line.replace(' SKRIVA UT ', ' SKRIVA_UT ')
    line = line.replace(' SKRUBBA AV ', ' SKRUBBA_AV ')
    line = line.replace(' SKRUDA SIG ', ' SKRUDA_SIG ')
    line = line.replace(' SKRUVA AV ', ' SKRUVA_AV ')
    line = line.replace(' SKRUVA IN ', ' SKRUVA_IN ')
    line = line.replace(' SKRUVA P@ ', ' SKRUVA_P@ ')
    line = line.replace(' SKRUVA SIG ', ' SKRUVA_SIG ')
    line = line.replace(' SKRUVA UPP ', ' SKRUVA_UPP ')
    line = line.replace(' SKRYNKLA SIG ', ' SKRYNKLA_SIG ')
    line = line.replace(' SKUDDA AV ', ' SKUDDA_AV ')
    line = line.replace(' SKUFFA TILL ', ' SKUFFA_TILL ')
    line = line.replace(' SKULDS$TTA SIG ', ' SKULDS$TTA_SIG ')
    line = line.replace(' SKULPTERA UT ', ' SKULPTERA_UT ')
    line = line.replace(' SKUMMA AV ', ' SKUMMA_AV ')
    line = line.replace(' SKURA AV ', ' SKURA_AV ')
    line = line.replace(' SKYGGA TILLBAKA ', ' SKYGGA_TILLBAKA ')
    line = line.replace(' SKYLLA IFR@N SIG ', ' SKYLLA_IFR@N_SIG ')
    line = line.replace(' SKYNDA SIG ', ' SKYNDA_SIG ')
    line = line.replace(' SL@ AN ', ' SL@_AN ')
    line = line.replace(' SL@ AV ', ' SL@_AV ')
    line = line.replace(' SL@ BORT ', ' SL@_BORT ')
    line = line.replace(' SL@ IN ', ' SL@_IN ')
    line = line.replace(' SL@ SIG ', ' SL@_SIG ')
    line = line.replace(' SL@ UPP ', ' SL@_UPP ')
    line = line.replace(' SL@ UT ', ' SL@_UT ')
    line = line.replace(' SL$NGA BORT ', ' SL$NGA_BORT ')
    line = line.replace(' SL$NGA SIG ', ' SL$NGA_SIG ')
    line = line.replace(' SL$PA IN ', ' SL$PA_IN ')
    line = line.replace(' SL$PPA AV ', ' SL$PPA_AV ')
    line = line.replace(' SL$PPA IN ', ' SL$PPA_IN ')
    line = line.replace(' SL$PPA SIG ', ' SL$PPA_SIG ')
    line = line.replace(' SL$PPA UT ', ' SL$PPA_UT ')
    line = line.replace(' SL$TA UT ', ' SL$TA_UT ')
    line = line.replace(' SLABBA NED ', ' SLABBA_NED ')
    line = line.replace(' SLAMMA IGEN ', ' SLAMMA_IGEN ')
    line = line.replace(' SLAPPNA AV ', ' SLAPPNA_AV ')
    line = line.replace(' SLARVA BORT ', ' SLARVA_BORT ')
    line = line.replace(' SLICKA AV ', ' SLICKA_AV ')
    line = line.replace(' SLICKA BORT ', ' SLICKA_BORT ')
    line = line.replace(' SLICKA I SIG ', ' SLICKA_I_SIG ')
    line = line.replace(' SLICKA UPP ', ' SLICKA_UPP ')
    line = line.replace(' SLINGRA SIG ', ' SLINGRA_SIG ')
    line = line.replace(' SLINKA IN ', ' SLINKA_IN ')
    line = line.replace(' SLIPA AV ', ' SLIPA_AV ')
    line = line.replace(' SLIPA BORT ', ' SLIPA_BORT ')
    line = line.replace(' SLITA AV ', ' SLITA_AV ')
    line = line.replace(' SLITA LOSS ', ' SLITA_LOSS ')
    line = line.replace(' SLITA UPP ', ' SLITA_UPP ')
    line = line.replace(' SLOCKNA AV ', ' SLOCKNA_AV ')
    line = line.replace(' SLUMPA SIG ', ' SLUMPA_SIG ')
    line = line.replace(' SLUMRA IN ', ' SLUMRA_IN ')
    line = line.replace(' SLUMRA TILL ', ' SLUMRA_TILL ')
    line = line.replace(' SLUNGA UT ', ' SLUNGA_UT ')
    line = line.replace(' SLUTA SIG ', ' SLUTA_SIG ')
    line = line.replace(' SLUTA UPP ', ' SLUTA_UPP ')
    line = line.replace(' SM#RJA IN ', ' SM#RJA_IN ')
    line = line.replace(' SM#RJA SIG ', ' SM#RJA_SIG ')
    line = line.replace(' SM$CKA TILL ', ' SM$CKA_TILL ')
    line = line.replace(' SM$LLA AV ', ' SM$LLA_AV ')
    line = line.replace(' SM$LTA AV ', ' SM$LTA_AV ')
    line = line.replace(' SM$LTA IN ', ' SM$LTA_IN ')
    line = line.replace(' SM$LTA NED ', ' SM$LTA_NED ')
    line = line.replace(' SMAKA AV ', ' SMAKA_AV ')
    line = line.replace(' SMAKA P@ ', ' SMAKA_P@ ')
    line = line.replace(' SMALNA AV ', ' SMALNA_AV ')
    line = line.replace(' SMINKA SIG ', ' SMINKA_SIG ')
    line = line.replace(' SMOCKA TILL ', ' SMOCKA_TILL ')
    line = line.replace(' SMUGGLA IN ', ' SMUGGLA_IN ')
    line = line.replace(' SMULA AV ', ' SMULA_AV ')
    line = line.replace(' SMULA SIG ', ' SMULA_SIG ')
    line = line.replace(' SMUSSLA IN ', ' SMUSSLA_IN ')
    line = line.replace(' SMUSSLA UNDAN ', ' SMUSSLA_UNDAN ')
    line = line.replace(' SMUTSA NED ', ' SMUTSA_NED ')
    line = line.replace(' SMYGA IN ', ' SMYGA_IN ')
    line = line.replace(' SMYGA SIG ', ' SMYGA_SIG ')
    line = line.replace(' SN@LA IN ', ' SN@LA_IN ')
    line = line.replace(' SN#A IN ', ' SN#A_IN ')
    line = line.replace(' SN#RA AV ', ' SN#RA_AV ')
    line = line.replace(' SN$RJA IN ', ' SN$RJA_IN ')
    line = line.replace(' SN$SA AV ', ' SN$SA_AV ')
    line = line.replace(' SN$VA IN ', ' SN$VA_IN ')
    line = line.replace(' SNABBA P@ ', ' SNABBA_P@ ')
    line = line.replace(' SNABBA SIG ', ' SNABBA_SIG ')
    line = line.replace(' SNABBA UPP ', ' SNABBA_UPP ')
    line = line.replace(' SNAPPA UPP ', ' SNAPPA_UPP ')
    line = line.replace(' SNEDDA AV ', ' SNEDDA_AV ')
    line = line.replace(' SNIGLA SIG FRAM ', ' SNIGLA_SIG_FRAM ')
    line = line.replace(' SNILLA UNDAN ', ' SNILLA_UNDAN ')
    line = line.replace(' SNO SIG ', ' SNO_SIG ')
    line = line.replace(' SNOFSA UPP SIG ', ' SNOFSA_UPP_SIG ')
    line = line.replace(' SNOKA UPP ', ' SNOKA_UPP ')
    line = line.replace(' SNOPPA AV ', ' SNOPPA_AV ')
    line = line.replace(' SNUSKA NER ', ' SNUSKA_NER ')
    line = line.replace(' SNYGGA UPP SIG ', ' SNYGGA_UPP_SIG ')
    line = line.replace(' SNYTA SIG ', ' SNYTA_SIG ')
    line = line.replace(' SOLA SIG ', ' SOLA_SIG ')
    line = line.replace(' SOLKA NED ', ' SOLKA_NED ')
    line = line.replace(' SOM ATT ', ' SOM_ATT ')
    line = line.replace(' SOM OM ', ' SOM_OM ')
    line = line.replace(' SOMNA AV ', ' SOMNA_AV ')
    line = line.replace(' SOMNA BORT ', ' SOMNA_BORT ')
    line = line.replace(' SOMNA IFR@N ', ' SOMNA_IFR@N ')
    line = line.replace(' SOMNA IN ', ' SOMNA_IN ')
    line = line.replace(' SOMNA OM ', ' SOMNA_OM ')
    line = line.replace(' SOMNA TILL ', ' SOMNA_TILL ')
    line = line.replace(' SOPA IGEN ', ' SOPA_IGEN ')
    line = line.replace(' SORTERA IN ', ' SORTERA_IN ')
    line = line.replace(' SOTA IGEN ', ' SOTA_IGEN ')
    line = line.replace(' SOVA UT ', ' SOVA_UT ')
    line = line.replace(' SP@RA UPP ', ' SP@RA_UPP ')
    line = line.replace(' SP#KA UT SIG ', ' SP#KA_UT_SIG ')
    line = line.replace(' SP$DA UT ', ' SP$DA_UT ')
    line = line.replace(' SP$KA SIG ', ' SP$KA_SIG ')
    line = line.replace(' SP$NNA @T ', ' SP$NNA_@T ')
    line = line.replace(' SP$NNA AV ', ' SP$NNA_AV ')
    line = line.replace(' SP$NNA F#R ', ' SP$NNA_F#R ')
    line = line.replace(' SP$NNA FAST ', ' SP$NNA_FAST ')
    line = line.replace(' SP$NNA FR@N ', ' SP$NNA_FR@N ')
    line = line.replace(' SP$NNA P@ ', ' SP$NNA_P@ ')
    line = line.replace(' SP$NNA UPP ', ' SP$NNA_UPP ')
    line = line.replace(' SP$NNA UT ', ' SP$NNA_UT ')
    line = line.replace(' SP$RRA AV ', ' SP$RRA_AV ')
    line = line.replace(' SP$RRA IN ', ' SP$RRA_IN ')
    line = line.replace(' SP$RRA UT ', ' SP$RRA_UT ')
    line = line.replace(' SPALTA UPP ', ' SPALTA_UPP ')
    line = line.replace(' SPARA IHOP ', ' SPARA_IHOP ')
    line = line.replace(' SPARKA AV ', ' SPARKA_AV ')
    line = line.replace(' SPARKA BORT ', ' SPARKA_BORT ')
    line = line.replace(' SPARKA IN ', ' SPARKA_IN ')
    line = line.replace(' SPARKA TILL ', ' SPARKA_TILL ')
    line = line.replace(' SPARKA UT ', ' SPARKA_UT ')
    line = line.replace(' SPECIALISERA SIG ', ' SPECIALISERA_SIG ')
    line = line.replace(' SPELA IN ', ' SPELA_IN ')
    line = line.replace(' SPELADE UPP ', ' SPELADE_UPP ')
    line = line.replace(' SPELA UPP ', ' SPELA_UPP ')
    line = line.replace(' SPELA UT ', ' SPELA_UT ')
    line = line.replace(' SPJ$RNA EMOT ', ' SPJ$RNA_EMOT ')
    line = line.replace(' SPLITTRA SIG ', ' SPLITTRA_SIG ')
    line = line.replace(' SPLITTRA UPP ', ' SPLITTRA_UPP ')
    line = line.replace(' SPOLA #VER ', ' SPOLA_#VER ')
    line = line.replace(' SPOLA AV ', ' SPOLA_AV ')
    line = line.replace(' SPOLA BORT ', ' SPOLA_BORT ')
    line = line.replace(' SPR$NGA AV ', ' SPR$NGA_AV ')
    line = line.replace(' SPR$NGA S#NDER ', ' SPR$NGA_S#NDER ')
    line = line.replace(' SPR$TTA BORT ', ' SPR$TTA_BORT ')
    line = line.replace(' SPR$TTA UPP ', ' SPR$TTA_UPP ')
    line = line.replace(' SPRICKA UPP ', ' SPRICKA_UPP ')
    line = line.replace(' SPRICKA UT ', ' SPRICKA_UT ')
    line = line.replace(' SPRIDA SIG ', ' SPRIDA_SIG ')
    line = line.replace(' SPRIDA UT ', ' SPRIDA_UT ')
    line = line.replace(' SPRINGA BORT ', ' SPRINGA_BORT ')
    line = line.replace(' SPRINGA F#RE ', ' SPRINGA_F#RE ')
    line = line.replace(' SPRINGA FATT ', ' SPRINGA_FATT ')
    line = line.replace(' SPRINGA FRAM ', ' SPRINGA_FRAM ')
    line = line.replace(' SPRINGA IFR@N ', ' SPRINGA_IFR@N ')
    line = line.replace(' SPRINGA OMKULL ', ' SPRINGA_OMKULL ')
    line = line.replace(' SPRINGA UT ', ' SPRINGA_UT ')
    line = line.replace(' SPRITTA TILL ', ' SPRITTA_TILL ')
    line = line.replace(' SPRITTA UPP ', ' SPRITTA_UPP ')
    line = line.replace(' SPRUTA IN ', ' SPRUTA_IN ')
    line = line.replace(' SPRUTA UT ', ' SPRUTA_UT ')
    line = line.replace(' SPY UPP ', ' SPY_UPP ')
    line = line.replace(' ST@ #VER ', ' ST@_#VER ')
    line = line.replace(' ST@ EFTER ', ' ST@_EFTER ')
    line = line.replace(' ST@ EMOT ', ' ST@_EMOT ')
    line = line.replace(' ST@ FAST ', ' ST@_FAST ')
    line = line.replace(' ST@ INNE ', ' ST@_INNE ')
    line = line.replace(' ST@ KVAR ', ' ST@_KVAR ')
    line = line.replace(' ST@ P@ ', ' ST@_P@ ')
    line = line.replace(' ST@ SIG ', ' ST@_SIG ')
    line = line.replace(' ST@ TILL ', ' ST@_TILL ')
    line = line.replace(' ST@ TILLBAKA ', ' ST@_TILLBAKA ')
    line = line.replace(' ST@ UPP ', ' ST@_UPP ')
    line = line.replace(' ST@ UT ', ' ST@_UT ')
    line = line.replace(' ST@LS$TTA SIG ', ' ST@LS$TTA_SIG ')
    line = line.replace(' ST#DA SIG ', ' ST#DA_SIG ')
    line = line.replace(' ST#DJA SIG ', ' ST#DJA_SIG ')
    line = line.replace(' ST#KA TILL ', ' ST#KA_TILL ')
    line = line.replace(' ST#RTA IN ', ' ST#RTA_IN ')
    line = line.replace(' ST#TA BORT ', ' ST#TA_BORT ')
    line = line.replace(' ST#TA P@ ', ' ST#TA_P@ ')
    line = line.replace(' ST#TA SIG ', ' ST#TA_SIG ')
    line = line.replace(' ST#TA TILL ', ' ST#TA_TILL ')
    line = line.replace(' ST#TTA UPP ', ' ST#TTA_UPP ')
    line = line.replace(' ST$LLA AV ', ' ST$LLA_AV ')
    line = line.replace(' ST$LLA BORT ', ' ST$LLA_BORT ')
    line = line.replace(' ST$LLA FRAM ', ' ST$LLA_FRAM ')
    line = line.replace(' ST$LLA I ORDNING ', ' ST$LLA_I_ORDNING ')
    line = line.replace(' ST$LLA IHOP ', ' ST$LLA_IHOP ')
    line = line.replace(' ST$LLA IN ', ' ST$LLA_IN ')
    line = line.replace(' ST$LLA OM ', ' ST$LLA_OM ')
    line = line.replace(' ST$LLA SIG ', ' ST$LLA_SIG ')
    line = line.replace(' ST$LLA TILL ', ' ST$LLA_TILL ')
    line = line.replace(' ST$LLA UNDAN ', ' ST$LLA_UNDAN ')
    line = line.replace(' ST$LLA UPP ', ' ST$LLA_UPP ')
    line = line.replace(' ST$LLA UT ', ' ST$LLA_UT ')
    line = line.replace(' ST$MMA #VERENS ', ' ST$MMA_#VERENS ')
    line = line.replace(' ST$MMA AV ', ' ST$MMA_AV ')
    line = line.replace(' ST$MMA IN ', ' ST$MMA_IN ')
    line = line.replace(' ST$MMA UPP ', ' ST$MMA_UPP ')
    line = line.replace(' ST$MPLA IN ', ' ST$MPLA_IN ')
    line = line.replace(' ST$NGA AV ', ' ST$NGA_AV ')
    line = line.replace(' ST$NGA IN ', ' ST$NGA_IN ')
    line = line.replace(' ST$NGA TILL ', ' ST$NGA_TILL ')
    line = line.replace(' ST$RKA SIG ', ' ST$RKA_SIG ')
    line = line.replace(' STADGA SIG ', ' STADGA_SIG ')
    line = line.replace(' STAKA SIG ', ' STAKA_SIG ')
    line = line.replace(' STAMPA NED ', ' STAMPA_NED ')
    line = line.replace(' STANNA AV ', ' STANNA_AV ')
    line = line.replace(' STANNA TILL ', ' STANNA_TILL ')
    line = line.replace(' STANNA UPP ', ' STANNA_UPP ')
    line = line.replace(' STANSA UT ', ' STANSA_UT ')
    line = line.replace(' STAPLA UPP ', ' STAPLA_UPP ')
    line = line.replace(' STARTA UPP ', ' STARTA_UPP ')
    line = line.replace(' STAVA AV ', ' STAVA_AV ')
    line = line.replace(' STICKA IN ', ' STICKA_IN ')
    line = line.replace(' STICKA SIG ', ' STICKA_SIG ')
    line = line.replace(' STICKA UT ', ' STICKA_UT ')
    line = line.replace(' STIGA AV ', ' STIGA_AV ')
    line = line.replace(' STIGA IN ', ' STIGA_IN ')
    line = line.replace(' STIGA P@ ', ' STIGA_P@ ')
    line = line.replace(' STILA SIG ', ' STILA_SIG ')
    line = line.replace(' STILLA SIG ', ' STILLA_SIG ')
    line = line.replace(' STJ$LPA AV ', ' STJ$LPA_AV ')
    line = line.replace(' STJ$LPA UPP ', ' STJ$LPA_UPP ')
    line = line.replace(' STOCKA SIG ', ' STOCKA_SIG ')
    line = line.replace(' STOPPA IGEN ', ' STOPPA_IGEN ')
    line = line.replace(' STOPPA IN ', ' STOPPA_IN ')
    line = line.replace(' STOPPA NED ', ' STOPPA_NED ')
    line = line.replace(' STOPPA UPP ', ' STOPPA_UPP ')
    line = line.replace(' STORMA IN ', ' STORMA_IN ')
    line = line.replace(' STR# UT ', ' STR#_UT ')
    line = line.replace(' STR#MMA IN ', ' STR#MMA_IN ')
    line = line.replace(' STR#MMA UT ', ' STR#MMA_UT ')
    line = line.replace(' STR$CKA SIG ', ' STR$CKA_SIG ')
    line = line.replace(' STR$CKA UT ', ' STR$CKA_UT ')
    line = line.replace(' STRAFFA SIG ', ' STRAFFA_SIG ')
    line = line.replace(' STRYKA UT ', ' STRYKA_UT ')
    line = line.replace(' STUVA IN ', ' STUVA_IN ')
    line = line.replace(' STYCKA AV ', ' STYCKA_AV ')
    line = line.replace(' STYCKA UPP ', ' STYCKA_UPP ')
    line = line.replace(' STYRA #VER ', ' STYRA_#VER ')
    line = line.replace(' STYRA IN ', ' STYRA_IN ')
    line = line.replace(' STYRA UT ', ' STYRA_UT ')
    line = line.replace(' SUGA AV ', ' SUGA_AV ')
    line = line.replace(' SUGA IN ', ' SUGA_IN ')
    line = line.replace(' SUGA UPP ', ' SUGA_UPP ')
    line = line.replace(' SUPA IN ', ' SUPA_IN ')
    line = line.replace(' SUPA SIG FULL ', ' SUPA_SIG_FULL ')
    line = line.replace(' SUPA UPP ', ' SUPA_UPP ')
    line = line.replace(' SURRA FAST ', ' SURRA_FAST ')
    line = line.replace(' SV$LJA NED ', ' SV$LJA_NED ')
    line = line.replace(' SV$LLA UPP ', ' SV$LLA_UPP ')
    line = line.replace(' SV$LLA UT ', ' SV$LLA_UT ')
    line = line.replace(' SV$LTA IHJ$L ', ' SV$LTA_IHJ$L ')
    line = line.replace(' SV$LTA SIG ', ' SV$LTA_SIG ')
    line = line.replace(' SV$LTA UT ', ' SV$LTA_UT ')
    line = line.replace(' SV$MMA #VER ', ' SV$MMA_#VER ')
    line = line.replace(' SV$NGA AV ', ' SV$NGA_AV ')
    line = line.replace(' SV$NGA IN ', ' SV$NGA_IN ')
    line = line.replace(' SV$NGA OM ', ' SV$NGA_OM ')
    line = line.replace(' SV$NGA RUNT ', ' SV$NGA_RUNT ')
    line = line.replace(' SV$NGA SIG ', ' SV$NGA_SIG ')
    line = line.replace(' SV$NGA UT ', ' SV$NGA_UT ')
    line = line.replace(' SV$RTA NED ', ' SV$RTA_NED ')
    line = line.replace(' SV$VA UT ', ' SV$VA_UT ')
    line = line.replace(' SVALKA AV ', ' SVALKA_AV ')
    line = line.replace(' SVALKA AV SIG ', ' SVALKA_AV_SIG ')
    line = line.replace(' SVALNA AV ', ' SVALNA_AV ')
    line = line.replace(' SVAMPA SIG ', ' SVAMPA_SIG ')
    line = line.replace(' SVARVA AV ', ' SVARVA_AV ')
    line = line.replace(' SVARVA BORT ', ' SVARVA_BORT ')
    line = line.replace(' SVARVA TILL ', ' SVARVA_TILL ')
    line = line.replace(' SVEPA F#RBI ', ' SVEPA_F#RBI ')
    line = line.replace(' SVEPA I SIG ', ' SVEPA_I_SIG ')
    line = line.replace(' SVEPA IN ', ' SVEPA_IN ')
    line = line.replace(' SVEPA OM SIG ', ' SVEPA_OM_SIG ')
    line = line.replace(' SVETSA IHOP ', ' SVETSA_IHOP ')
    line = line.replace(' SVETTA UT ', ' SVETTA_UT ')
    line = line.replace(' SVIDA OM ', ' SVIDA_OM ')
    line = line.replace(' SVIMMA AV ', ' SVIMMA_AV ')
    line = line.replace(' SVINA NED ', ' SVINA_NED ')
    line = line.replace(' SVINGA SIG UPP ', ' SVINGA_SIG_UPP ')
    line = line.replace(' SVULLNA IGEN ', ' SVULLNA_IGEN ')
    line = line.replace(' SVULLNA UPP ', ' SVULLNA_UPP ')
    line = line.replace(' SY AV ', ' SY_AV ')
    line = line.replace(' SYLTA IN ', ' SYLTA_IN ')
    line = line.replace(' SYNA AV ', ' SYNA_AV ')
    line = line.replace(' T EX ', ' T_EX ')
    line = line.replace(' T@GA IN ', ' T@GA_IN ')
    line = line.replace(' T@GA UT ', ' T@GA_UT ')
    line = line.replace(' T@LA SIG ', ' T@LA_SIG ')
    line = line.replace(' T@RA SIG ', ' T@RA_SIG ')
    line = line.replace(' T#A BORT ', ' T#A_BORT ')
    line = line.replace(' T#JA SIG ', ' T#JA_SIG ')
    line = line.replace(' T#MMA UT ', ' T#MMA_UT ')
    line = line.replace(' T#NTA SIG ', ' T#NTA_SIG ')
    line = line.replace(' T#RNA IHOP ', ' T#RNA_IHOP ')
    line = line.replace(' T#RNA IN ', ' T#RNA_IN ')
    line = line.replace(' T#RNA MOT ', ' T#RNA_MOT ')
    line = line.replace(' T$CKA #VER ', ' T$CKA_#VER ')
    line = line.replace(' T$CKA AV ', ' T$CKA_AV ')
    line = line.replace(' T$LJA AV ', ' T$LJA_AV ')
    line = line.replace(' T$NDA P@ ', ' T$NDA_P@ ')
    line = line.replace(' T$NJA UT ', ' T$NJA_UT ')
    line = line.replace(' T$PPA IGEN ', ' T$PPA_IGEN ')
    line = line.replace(' T$PPA TILL ', ' T$PPA_TILL ')
    line = line.replace(' TA @T SIG ', ' TA_@T_SIG ')
    line = line.replace(' TA #VER ', ' TA_#VER ')
    line = line.replace(' TA AV ', ' TA_AV ')
    line = line.replace(' TA AV SIG ', ' TA_AV_SIG ')
    line = line.replace(' TA BORT ', ' TA_BORT ')
    line = line.replace(' TA EFTER ', ' TA_EFTER ')
    line = line.replace(' TA EMOT ', ' TA_EMOT ')
    line = line.replace(' TA F#R SIG ', ' TA_F#R_SIG ')
    line = line.replace(' TA FATT I ', ' TA_FATT_I ')
    line = line.replace(' TA FRAM ', ' TA_FRAM ')
    line = line.replace(' TA IFR@N ', ' TA_IFR@N ')
    line = line.replace(' TA IGEN ', ' TA_IGEN ')
    line = line.replace(' TA IGEN SIG ', ' TA_IGEN_SIG ')
    line = line.replace(' TA IN ', ' TA_IN ')
    line = line.replace(' TA IN P@ ', ' TA_IN_P@ ')
    line = line.replace(' TA IS$R ', ' TA_IS$R ')
    line = line.replace(' TA MED ', ' TA_MED ')
    line = line.replace(' TA NED ', ' TA_NED ')
    line = line.replace(' TA P@ ', ' TA_P@ ')
    line = line.replace(' TA P@ SIG ', ' TA_P@_SIG ')
    line = line.replace(' TA SIG ', ' TA_SIG ')
    line = line.replace(' TA SIG F#R ', ' TA_SIG_F#R ')
    line = line.replace(' TA SIG FRAM ', ' TA_SIG_FRAM ')
    line = line.replace(' TA SIG TILL ', ' TA_SIG_TILL ')
    line = line.replace(' TA SIG UPP ', ' TA_SIG_UPP ')
    line = line.replace(' TA SIG UT ', ' TA_SIG_UT ')
    line = line.replace(' TA TILL ', ' TA_TILL ')
    line = line.replace(' TA TILLBAKA ', ' TA_TILLBAKA ')
    line = line.replace(' TA UPP ', ' TA_UPP ')
    line = line.replace(' TA UR ', ' TA_UR ')
    line = line.replace(' TA UT ', ' TA_UT ')
    line = line.replace(' TA VID SIG ', ' TA_VID_SIG ')
    line = line.replace(' TACKA AV ', ' TACKA_AV ')
    line = line.replace(' TACKLA AV ', ' TACKLA_AV ')
    line = line.replace(' TAGA AV ', ' TAGA_AV ')
    line = line.replace(' TALA IN ', ' TALA_IN ')
    line = line.replace(' TALA OM ', ' TALA_OM ')
    line = line.replace(' TALA UT ', ' TALA_UT ')
    line = line.replace(' TAPPA AV ', ' TAPPA_AV ')
    line = line.replace(' TAPPA BORT ', ' TAPPA_BORT ')
    line = line.replace(' TAPPA I ', ' TAPPA_I ')
    line = line.replace(' TAPPA UPP ', ' TAPPA_UPP ')
    line = line.replace(' TASSA IN ', ' TASSA_IN ')
    line = line.replace(' TATUERA IN ', ' TATUERA_IN ')
    line = line.replace(' TE SIG ', ' TE_SIG ')
    line = line.replace(' TECKNA AV ', ' TECKNA_AV ')
    line = line.replace(' TIGGA SIG TILL ', ' TIGGA_SIG_TILL ')
    line = line.replace(' TILL #VERS ', ' TILL_#VERS ')
    line = line.replace(' TILL BORDS ', ' TILL_BORDS ')
    line = line.replace(' TILL BUDS ', ' TILL_BUDS ')
    line = line.replace(' TILL D#DS ', ' TILL_D#DS ')
    line = line.replace(' TILL DESS ', ' TILL_DESS ')
    line = line.replace(' TILL FOTS ', ' TILL_FOTS ')
    line = line.replace(' TILL FREDS ', ' TILL_FREDS ')
    line = line.replace(' TILL HANDS ', ' TILL_HANDS ')
    line = line.replace(' TILL HAVS ', ' TILL_HAVS ')
    line = line.replace(' TILL L@NS ', ' TILL_L@NS ')
    line = line.replace(' TILL LAGS ', ' TILL_LAGS ')
    line = line.replace(' TILL LANDS ', ' TILL_LANDS ')
    line = line.replace(' TILL LIVS ', ' TILL_LIVS ')
    line = line.replace(' TILL MANS ', ' TILL_MANS ')
    line = line.replace(' TILL MODS ', ' TILL_MODS ')
    line = line.replace(' TILL S$NGS ', ' TILL_S$NGS ')
    line = line.replace(' TILL SJ#SS ', ' TILL_SJ#SS ')
    line = line.replace(' TILL SKOGS ', ' TILL_SKOGS ')
    line = line.replace(' TILL$GNA SIG ', ' TILL$GNA_SIG ')
    line = line.replace(' TILLK$MPA SIG ', ' TILLK$MPA_SIG ')
    line = line.replace(' TILLV$LLA SIG ', ' TILLV$LLA_SIG ')
    line = line.replace(' TINA AV ', ' TINA_AV ')
    line = line.replace(' TINA UPP ', ' TINA_UPP ')
    line = line.replace(' TJ$NA AV ', ' TJ$NA_AV ')
    line = line.replace(' TJ$NA IN ', ' TJ$NA_IN ')
    line = line.replace(' TJATA SIG TILL ', ' TJATA_SIG_TILL ')
    line = line.replace(' TJORVA TILL SIG ', ' TJORVA_TILL_SIG ')
    line = line.replace(' TONA AV ', ' TONA_AV ')
    line = line.replace(' TONA NER ', ' TONA_NER ')
    line = line.replace(' TORKA AV ', ' TORKA_AV ')
    line = line.replace(' TORKA IN ', ' TORKA_IN ')
    line = line.replace(' TORKA UPP ', ' TORKA_UPP ')
    line = line.replace(' TORNA UPP ', ' TORNA_UPP ')
    line = line.replace(' TOTA IHOP ', ' TOTA_IHOP ')
    line = line.replace(' TOTA TILL ', ' TOTA_TILL ')
    line = line.replace(' TOVA SIG ', ' TOVA_SIG ')
    line = line.replace(' TR@KA UT ', ' TR@KA_UT ')
    line = line.replace(' TR#TTA UT ', ' TR#TTA_UT ')
    line = line.replace(' TR$ P@ ', ' TR$_P@ ')
    line = line.replace(' TR$DA IN ', ' TR$DA_IN ')
    line = line.replace(' TR$DA P@ ', ' TR$DA_P@ ')
    line = line.replace(' TR$NA IN ', ' TR$NA_IN ')
    line = line.replace(' TR$NA SIG ', ' TR$NA_SIG ')
    line = line.replace(' TR$NA UPP ', ' TR$NA_UPP ')
    line = line.replace(' TR$NGA IN ', ' TR$NGA_IN ')
    line = line.replace(' TR$NGA SIG P@ ', ' TR$NGA_SIG_P@ ')
    line = line.replace(' TR$NGA UT ', ' TR$NGA_UT ')
    line = line.replace(' TRAMPA AV ', ' TRAMPA_AV ')
    line = line.replace(' TRAMPA BORT ', ' TRAMPA_BORT ')
    line = line.replace(' TRAMPA FEL ', ' TRAMPA_FEL ')
    line = line.replace(' TRAMPA IG@NG ', ' TRAMPA_IG@NG ')
    line = line.replace(' TRAMPA IGENOM ', ' TRAMPA_IGENOM ')
    line = line.replace(' TRAMPA IHJ$L ', ' TRAMPA_IHJ$L ')
    line = line.replace(' TRAMPA NED ', ' TRAMPA_NED ')
    line = line.replace(' TRAMPA NER ', ' TRAMPA_NER ')
    line = line.replace(' TRAMPA P@ ', ' TRAMPA_P@ ')
    line = line.replace(' TRAMPA S#NDER ', ' TRAMPA_S#NDER ')
    line = line.replace(' TRAMPA UPP ', ' TRAMPA_UPP ')
    line = line.replace(' TRAPPA AV ', ' TRAPPA_AV ')
    line = line.replace(' TRAPPA NED ', ' TRAPPA_NED ')
    line = line.replace(' TRAPPA UPP ', ' TRAPPA_UPP ')
    line = line.replace(' TRASA S#NDER ', ' TRASA_S#NDER ')
    line = line.replace(' TRASKA DIT ', ' TRASKA_DIT ')
    line = line.replace(' TRASKA FRAM ', ' TRASKA_FRAM ')
    line = line.replace(' TRASKA HEM@T ', ' TRASKA_HEM@T ')
    line = line.replace(' TRASKA KRING ', ' TRASKA_KRING ')
    line = line.replace(' TRASKA MED ', ' TRASKA_MED ')
    line = line.replace(' TRASKA P@ ', ' TRASKA_P@ ')
    line = line.replace(' TRASSLA IN ', ' TRASSLA_IN ')
    line = line.replace(' TRASSLA IN SIG ', ' TRASSLA_IN_SIG ')
    line = line.replace(' TRASSLA SIG ', ' TRASSLA_SIG ')
    line = line.replace(' TRASSLA TILL ', ' TRASSLA_TILL ')
    line = line.replace(' TRATTA I ', ' TRATTA_I ')
    line = line.replace(' TREVA SIG FRAM ', ' TREVA_SIG_FRAM ')
    line = line.replace(' TRILSKNA TILL ', ' TRILSKNA_TILL ')
    line = line.replace(' TRIMMA IN ', ' TRIMMA_IN ')
    line = line.replace(' TRISSA UPP ', ' TRISSA_UPP ')
    line = line.replace(' TROLLA BORT ', ' TROLLA_BORT ')
    line = line.replace(' TROLLA FRAM ', ' TROLLA_FRAM ')
    line = line.replace(' TROLOVA SIG ', ' TROLOVA_SIG ')
    line = line.replace(' TROPPA AV ', ' TROPPA_AV ')
    line = line.replace(' TRUBBA AV ', ' TRUBBA_AV ')
    line = line.replace(' TRULSA SIG ', ' TRULSA_SIG ')
    line = line.replace(' TRUMFA IGENOM ', ' TRUMFA_IGENOM ')
    line = line.replace(' TRYCKA AV ', ' TRYCKA_AV ')
    line = line.replace(' TRYCKA IN ', ' TRYCKA_IN ')
    line = line.replace(' TRYCKA NED ', ' TRYCKA_NED ')
    line = line.replace(' TRYCKA UT ', ' TRYCKA_UT ')
    line = line.replace(' TUFFA TILL SIG ', ' TUFFA_TILL_SIG ')
    line = line.replace(' TUFSA TILL ', ' TUFSA_TILL ')
    line = line.replace(' TUNNA UT ', ' TUNNA_UT ')
    line = line.replace(' TUPPA AV ', ' TUPPA_AV ')
    line = line.replace(' TURAS OM ', ' TURAS_OM ')
    line = line.replace(' TUSSA IHOP ', ' TUSSA_IHOP ')
    line = line.replace(' TUTTA P@ ', ' TUTTA_P@ ')
    line = line.replace(' TUTTI FRUTTI ', ' TUTTI_FRUTTI ')
    line = line.replace(' TUVA SIG ', ' TUVA_SIG ')
    line = line.replace(' TV@LA IN ', ' TV@LA_IN ')
    line = line.replace(' TV$TTA AV ', ' TV$TTA_AV ')
    line = line.replace(' TV$TTA BORT ', ' TV$TTA_BORT ')
    line = line.replace(' TVINA AV ', ' TVINA_AV ')
    line = line.replace(' TVINA BORT ', ' TVINA_BORT ')
    line = line.replace(' TVINGA AV ', ' TVINGA_AV ')
    line = line.replace(' TVINGA IN ', ' TVINGA_IN ')
    line = line.replace(' TY SIG ', ' TY_SIG ')
    line = line.replace(' TYCKA OM ', ' TYCKA_OM ')
    line = line.replace(' TYNA AV ', ' TYNA_AV ')
    line = line.replace(' TYNA BORT ', ' TYNA_BORT ')
    line = line.replace(' TYNGA NER ', ' TYNGA_NER ')
    line = line.replace(' TYSTA NED ', ' TYSTA_NED ')
    line = line.replace(' UNDERORDNA SIG ', ' UNDERORDNA_SIG ')
    line = line.replace(' UNDERST@ SIG ', ' UNDERST@_SIG ')
    line = line.replace(' UNDSKYLLA SIG ', ' UNDSKYLLA_SIG ')
    line = line.replace(' UNI SEX ', ' UNI_SEX ')
    line = line.replace(' UNKNA TILL ', ' UNKNA_TILL ')
    line = line.replace(' UNNA SIG ', ' UNNA_SIG ')
    line = line.replace(' UPPENBARA SIG ', ' UPPENBARA_SIG ')
    line = line.replace(' UPPOFFRA SIG ', ' UPPOFFRA_SIG ')
    line = line.replace(' URS$KTA SIG ', ' URS$KTA_SIG ')
    line = line.replace(' URSKULDA SIG ', ' URSKULDA_SIG ')
    line = line.replace(' UTBREDA SIG ', ' UTBREDA_SIG ')
    line = line.replace(' UTF$STA SIG ', ' UTF$STA_SIG ')
    line = line.replace(' UTGE SIG F#R ', ' UTGE_SIG_F#R ')
    line = line.replace(' UTKRISTALLISERA SIG ', ' UTKRISTALLISERA_SIG ')
    line = line.replace(' UTOM SIG ', ' UTOM_SIG ')
    line = line.replace(' UTSPINNA SIG ', ' UTSPINNA_SIG ')
    line = line.replace(' UTTALA SIG ', ' UTTALA_SIG ')
    line = line.replace(' V@GA SIG ', ' V@GA_SIG ')
    line = line.replace(' V@GA SIG IN ', ' V@GA_SIG_IN ')
    line = line.replace(' V@GA SIG P@ ', ' V@GA_SIG_P@ ')
    line = line.replace(' V@RDA SIG ', ' V@RDA_SIG ')
    line = line.replace(' V$CKA UPP ', ' V$CKA_UPP ')
    line = line.replace(' V$DRA UT ', ' V$DRA_UT ')
    line = line.replace(' V$GA AV ', ' V$GA_AV ')
    line = line.replace(' V$GA IN ', ' V$GA_IN ')
    line = line.replace(' V$GA SIG ', ' V$GA_SIG ')
    line = line.replace(' V$GA UPP ', ' V$GA_UPP ')
    line = line.replace(' V$LJA BORT ', ' V$LJA_BORT ')
    line = line.replace(' V$LJA IN ', ' V$LJA_IN ')
    line = line.replace(' V$LJA UT ', ' V$LJA_UT ')
    line = line.replace(' V$LLA FRAM ', ' V$LLA_FRAM ')
    line = line.replace(' V$LTA UT ', ' V$LTA_UT ')
    line = line.replace(' V$LTRA AV ', ' V$LTRA_AV ')
    line = line.replace(' V$LTRA OMKULL ', ' V$LTRA_OMKULL ')
    line = line.replace(' V$LTRA SIG ', ' V$LTRA_SIG ')
    line = line.replace(' V$LTRA UNDAN ', ' V$LTRA_UNDAN ')
    line = line.replace(' V$LVA SIG ', ' V$LVA_SIG ')
    line = line.replace(' V$NDA @TER ', ' V$NDA_@TER ')
    line = line.replace(' V$NDA OM ', ' V$NDA_OM ')
    line = line.replace(' V$NDA SIG ', ' V$NDA_SIG ')
    line = line.replace(' V$NDA TILLBAKA ', ' V$NDA_TILLBAKA ')
    line = line.replace(' V$NJA AV ', ' V$NJA_AV ')
    line = line.replace(' V$NJA SIG ', ' V$NJA_SIG ')
    line = line.replace(' V$NTA IN ', ' V$NTA_IN ')
    line = line.replace(' V$NTA SIG ', ' V$NTA_SIG ')
    line = line.replace(' V$NTA UT ', ' V$NTA_UT ')
    line = line.replace(' V$PNA SIG ', ' V$PNA_SIG ')
    line = line.replace(' V$RJA SIG ', ' V$RJA_SIG ')
    line = line.replace(' V$RMA UPP ', ' V$RMA_UPP ')
    line = line.replace(' V$TA NER ', ' V$TA_NER ')
    line = line.replace(' V$TSKA SIG ', ' V$TSKA_SIG ')
    line = line.replace(' V$VA IN ', ' V$VA_IN ')
    line = line.replace(' V$VA UPP ', ' V$VA_UPP ')
    line = line.replace(' V$XA BORT ', ' V$XA_BORT ')
    line = line.replace(' V$XA FAST ', ' V$XA_FAST ')
    line = line.replace(' V$XA FRAM ', ' V$XA_FRAM ')
    line = line.replace(' V$XA I ', ' V$XA_I ')
    line = line.replace(' V$XA IGEN ', ' V$XA_IGEN ')
    line = line.replace(' V$XA IHOP ', ' V$XA_IHOP ')
    line = line.replace(' V$XA IN ', ' V$XA_IN ')
    line = line.replace(' V$XA OM ', ' V$XA_OM ')
    line = line.replace(' V$XA TILL SIG ', ' V$XA_TILL_SIG ')
    line = line.replace(' V$XA UPP ', ' V$XA_UPP ')
    line = line.replace(' V$XA UR ', ' V$XA_UR ')
    line = line.replace(' V$XA UT ', ' V$XA_UT ')
    line = line.replace(' V$XLA IN ', ' V$XLA_IN ')
    line = line.replace(' V$XLA OM ', ' V$XLA_OM ')
    line = line.replace(' V$XLA TILL SIG ', ' V$XLA_TILL_SIG ')
    line = line.replace(' VA DE $R ', ' VA_DE_$R ')
    line = line.replace(' VA DE E ', ' VA_DE_E ')
    line = line.replace(' VA DET $R ', ' VA_DET_$R ')
    line = line.replace(' VACKLA TILL ', ' VACKLA_TILL ')
    line = line.replace(' VAD DE $R ', ' VAD_DE_$R ')
    line = line.replace(' VAD DE E ', ' VAD_DE_E ')
    line = line.replace(' VAD DET $R ', ' VAD_DET_$R ')
    line = line.replace(' VAD KUL ', ' VAD_KUL ')
    line = line.replace(' VAD ROLIGT ', ' VA_ROLIGT ')
    line = line.replace(' VAKNA TILL ', ' VAKNA_TILL ')
    line = line.replace(' VAKNA UPP ', ' VAKNA_UPP ')
    line = line.replace(' VAKTA UT ', ' VAKTA_UT ')
    line = line.replace(' VALKA SIG ', ' VALKA_SIG ')
    line = line.replace(' VALLA IGEN ', ' VALLA_IGEN ')
    line = line.replace(' VALLA IN ', ' VALLA_IN ')
    line = line.replace(' VAN DUeRENS V$G ', ' VAN_DUeRENS_V$G ')
    line = line.replace(' VAN GOGH ', ' VAN_GOGH ')
    line = line.replace(' VANDRA OMKRING ', ' VANDRA_OMKRING ')
    line = line.replace(' VAR SIN ', ' VAR_SIN ')
    line = line.replace(' VARA #VER ', ' VARA_#VER ')
    line = line.replace(' VARA AV MED ', ' VARA_AV_MED ')
    line = line.replace(' VARA BORTA ', ' VARA_BORTA ')
    line = line.replace(' VARA F#RE ', ' VARA_F#RE ')
    line = line.replace(' VARA IFR@N SIG ', ' VARA_IFR@N_SIG ')
    line = line.replace(' VARA MED ', ' VARA_MED ')
    line = line.replace(' VARA MED OM ', ' VARA_MED_OM ')
    line = line.replace(' VARA OM SIG ', ' VARA_OM_SIG ')
    line = line.replace(' VARA SIG ', ' VARA_SIG ')
    line = line.replace(' VARA TILL ', ' VARA_TILL ')
    line = line.replace(' VARA TILL SIG ', ' VARA_TILL_SIG ')
    line = line.replace(' VARA TILLBAKA ', ' VARA_TILLBAKA ')
    line = line.replace(' VARA UPPE ', ' VARA_UPPE ')
    line = line.replace(' VARA UTAN ', ' VARA_UTAN ')
    line = line.replace(' VARA UTE ', ' VARA_UTE ')
    line = line.replace(' VARA UTOM SIG ', ' VARA_UTOM_SIG ')
    line = line.replace(' VARE $R ', ' VARE_$R ')
    line = line.replace(' VARE E ', ' VARE_E ')
    line = line.replace(' VARE SIG ', ' VARE_SIG ')
    line = line.replace(' VARKUNNA SIG ', ' VARKUNNA_SIG ')
    line = line.replace(' VASKA AV ', ' VASKA_AV ')
    line = line.replace(' VECKLA IN ', ' VECKLA_IN ')
    line = line.replace(' VECKLA IN SIG ', ' VECKLA_IN_SIG ')
    line = line.replace(' VECKLA UT ', ' VECKLA_UT ')
    line = line.replace(' VETA AV ', ' VETA_AV ')
    line = line.replace(' VETA MED SIG ', ' VETA_MED_SIG ')
    line = line.replace(' VETA OM ', ' VETA_OM ')
    line = line.replace(' VETA SIG ', ' VETA_SIG ')
    line = line.replace(' VEVA NED ', ' VEVA_NED ')
    line = line.replace(' VEVA UPP ', ' VEVA_UPP ')
    line = line.replace(' VIDGA SIG ', ' VIDGA_SIG ')
    line = line.replace(' VIFTA BORT ', ' VIFTA_BORT ')
    line = line.replace(' VIGA SIG ', ' VIGA_SIG ')
    line = line.replace(' VIKA AV ', ' VIKA_AV ')
    line = line.replace(' VIKA IHOP ', ' VIKA_IHOP ')
    line = line.replace(' VIKA IN ', ' VIKA_IN ')
    line = line.replace(' VIKA NER ', ' VIKA_NER ')
    line = line.replace(' VIKA SIG ', ' VIKA_SIG ')
    line = line.replace(' VIKA TILLBAKA ', ' VIKA_TILLBAKA ')
    line = line.replace(' VIKA UNDAN ', ' VIKA_UNDAN ')
    line = line.replace(' VIKA UPP ', ' VIKA_UPP ')
    line = line.replace(' VIKA UT ', ' VIKA_UT ')
    line = line.replace(' VIKTA IN ', ' VIKTA_IN ')
    line = line.replace(' VILA SIG ', ' VILA_SIG ')
    line = line.replace(' VILA UPP SIG ', ' VILA_UPP_SIG ')
    line = line.replace(' VILA UT ', ' VILA_UT ')
    line = line.replace(' VILJA SIG ', ' VILJA_SIG ')
    line = line.replace(' VILLA BORT ', ' VILLA_BORT ')
    line = line.replace(' VINDA AV ', ' VINDA_AV ')
    line = line.replace(' VINDA OM ', ' VINDA_OM ')
    line = line.replace(' VINDA UPP ', ' VINDA_UPP ')
    line = line.replace(' VINGLA TILL ', ' VINGLA_TILL ')
    line = line.replace(' VINKA BORT ', ' VINKA_BORT ')
    line = line.replace(' VIRA IN ', ' VIRA_IN ')
    line = line.replace(' VIRA OM ', ' VIRA_OM ')
    line = line.replace(' VIRRA OMKRING ', ' VIRRA_OMKRING ')
    line = line.replace(' VIRVLA F#RBI ', ' VIRVLA_F#RBI ')
    line = line.replace(' VISA BORT ', ' VISA_BORT ')
    line = line.replace(' VISA IN ', ' VISA_IN ')
    line = line.replace(' VISA SIG ', ' VISA_SIG ')
    line = line.replace(' VISA UPP ', ' VISA_UPP ')
    line = line.replace(' VISA UT ', ' VISA_UT ')
    line = line.replace(' VISPA UPP ', ' VISPA_UPP ')
    line = line.replace(' VISSLA UT ', ' VISSLA_UT ')
    line = line.replace(' VISSNA AV ', ' VISSNA_AV ')
    line = line.replace(' VITTRA AV ', ' VITTRA_AV ')
    line = line.replace(' VITTRA BORT ', ' VITTRA_BORT ')
    line = line.replace(' VON BAHRS V$G ', ' VON_BAHRS_V$G ')
    line = line.replace(' VON BOIJGATAN ', ' VON_BOIJGATAN ')
    line = line.replace(' VON D#BELNS V$G ', ' VON_D#BELNS_V$G ')
    line = line.replace(' VON ESSEN ', ' VON_ESSEN ')
    line = line.replace(' VON KNORRING ', ' VON_KNORRING ')
    line = line.replace(' VON LINGENS V$G ', ' VON_LINGENS_V$G ')
    line = line.replace(' VON PLATENSGATAN ', ' VON_PLATENSGATAN ')
    line = line.replace(' VON ROSENS V$G ', ' VON_ROSENS_V$G ')
    line = line.replace(' VON TROILS V$G ', ' VON_TROILS_V$G ')
    line = line.replace(' VR$KA OMKULL ', ' VR$KA_OMKULL ')
    line = line.replace(' VR$KA SIG ', ' VR$KA_SIG ')
    line = line.replace(' VR$KA UR SIG ', ' VR$KA_UR_SIG ')
    line = line.replace(' VRAKA BORT ', ' VRAKA_BORT ')
    line = line.replace(' VRIDA AV ', ' VRIDA_AV ')
    line = line.replace(' VRIDA OM ', ' VRIDA_OM ')
    line = line.replace(' VRIDA SIG ', ' VRIDA_SIG ')
    line = line.replace(' VRIDA UPP ', ' VRIDA_UPP ')
    line = line.replace(' YMPA IN ', ' YMPA_IN ')
    line = line.replace(' YNGLA AV SIG ', ' YNGLA_AV_SIG ')
    line = line.replace(' YNKA SIG ', ' YNKA_SIG ')
    line = line.replace(' YPPA SIG ', ' YPPA_SIG ')
    line = line.replace(' YSTA SIG ', ' YSTA_SIG ')
    line = line.replace(' YTTRA SIG ', ' YTTRA_SIG ')
    line = line.replace(' YVA SIG ', ' YVA_SIG ')
    line = line.replace(' ZOOMA IN ', ' ZOOMA_IN ')
    line = line.replace(' P@ V$G ', ' P@_V$G ')
    line = line.replace('_P@ V$G ', ' P@_V$G ')
    line = line.replace('_P@ GRUND AV ', ' P@_GRUND_AV ')

    ## R sandhi and elisions
    line = line.replace('A @', 'A_ @')
    line = line.replace('A #', 'A_ #')
    line = line.replace('A $', 'A_ $')
    line = line.replace('A A', 'A_ A')
    line = line.replace('A E', 'A_ E')
    line = line.replace('A I', 'A_ I')
    line = line.replace('A O', 'A_ O')
    line = line.replace('A U', 'A_ U')
    line = line.replace('A Y', 'A_ Y')
    line = line.replace('E A', 'E_ A')
    line = line.replace('E $', 'E_ $')
    line = line.replace('E E', 'E_ E')
    line = line.replace('D DR', 'D _DR')
    line = line.replace('L DR', 'L _DR')
    line = line.replace('N DR', 'N _DR')
    line = line.replace('S DR', 'S _DR')
    line = line.replace('T DR', 'T _DR')
    line = line.replace('R D', 'R_ _D')
    line = line.replace('RN D', 'RN _D')
    line = line.replace('RD D', 'RD _D')
    line = line.replace('RT D', 'RT _D')
    line = line.replace('RS D', 'RS _D')
    line = line.replace('R N', 'R_ _N')
    line = line.replace('RN N', 'RN _N')
    line = line.replace('RD N', 'RD _N')
    line = line.replace('RT N', 'RT _N')
    line = line.replace('RS N', 'RS _N')
    line = line.replace('R KNOCK', 'R_ _KNOCK')
    line = line.replace('RN KNOCK', 'RN _KNOCK')
    line = line.replace('RD KNOCK', 'RD _KNOCK')
    line = line.replace('RT KNOCK', 'RT _KNOCK')
    line = line.replace('RS KNOCK', 'RS _KNOCK')
    line = line.replace('R S', 'R_ _S')
    line = line.replace('RN S', 'RN _S')
    line = line.replace('RD S', 'RD _S')
    line = line.replace('RT S', 'RT _S')
    line = line.replace('RS S', 'RS _S')
    line = line.replace('R_ _SCH', 'R SCH')
    line = line.replace('R_ _SH', 'R SH')
    line = line.replace('R_ _SJ', 'R SJ')
    line = line.replace('R_ _SKI', 'R SKI')
    line = line.replace('R_ _SKE', 'R SKE')
    line = line.replace('R_ _SKY', 'R SKY')
    line = line.replace('R_ _SK#', 'R SK#')
    line = line.replace('R_ _SK$', 'R SK$')
    line = line.replace('R_ _STJ', 'R STJ')
    line = line.replace('R_ _SSJ', 'R SSJ')
    line = line.replace('R CAE', 'R_ _CAE')
    line = line.replace('RN CAE', 'RN _CAE')
    line = line.replace('RD CAE', 'RD _CAE')
    line = line.replace('RT CAE', 'RT _CAE')
    line = line.replace('RS CAE', 'RS _CAE')
    line = line.replace('R CD', 'R_ _CD')
    line = line.replace('RN CD', 'RN _CD')
    line = line.replace('RD CD', 'RD _CD')
    line = line.replace('RT CD', 'RT _CD')
    line = line.replace('RS CD', 'RS _CD')
    line = line.replace('R CE', 'R_ _CE')
    line = line.replace('RN CE', 'RN _CE')
    line = line.replace('RD CE', 'RD _CE')
    line = line.replace('RT CE', 'RT _CE')
    line = line.replace('RS CE', 'RS _CE')
    line = line.replace('R CI', 'R_ _CI')
    line = line.replace('RN CI', 'RN _CI')
    line = line.replace('RD CI', 'RD _CI')
    line = line.replace('RT CI', 'RT _CI')
    line = line.replace('RS CI', 'RS _CI')
    line = line.replace('R CY', 'R_ _CY')
    line = line.replace('RN CY', 'RN _CY')
    line = line.replace('RD CY', 'RD _CY')
    line = line.replace('RT CY', 'RT _CY')
    line = line.replace('RS CY', 'RS _CY')
    line = line.replace('R PSAL', 'R_ _PSAL')
    line = line.replace('RN PSAL', 'RN _PSAL')
    line = line.replace('RD PSAL', 'RD _PSAL')
    line = line.replace('RT PSAL', 'RT _PSAL')
    line = line.replace('RS PSAL', 'RS _PSAL')
    line = line.replace('R R', 'R_ R')
    line = line.replace('R T', 'R_ _T')
    line = line.replace('RN T', 'RN _T')
    line = line.replace('RD T', 'RD _T')
    line = line.replace('RT T', 'RT _T')
    line = line.replace('RS T', 'RS _T')

    ## split hyphenated words (but keep truncated words as they are!)
    ## NOTE:  This also affects the interjections "huh-uh", "uh-huh" and "uh-oh".
    ## However, should work fine just aligning individual components.
    line = hyphenated.sub(r'\1 \2', line)
    line = hyphenated.sub(r'\1 \2', line)   ## do this twice for words like "daughter-in-law"
    
    ## split line into words:
    words = line.split()

    ## add uncertainty parentheses around every word individually
    newwords = []
    for word in words:
        if word == "((":        ## beginning of uncertain transcription span
            if not flag_uncertain:
                flag_uncertain = True
                last_beg_uncertain = original_line
            else:   ## This should not happen! (but might because of transcription errors)
                error = "ERROR!  Beginning of uncertain transcription span detected twice in a row:  %s.  Please close the the opening double parenthesis in line %s." % (original_line, last_beg_uncertain)
                errorhandler(error)
        elif word == "))":      ## end of uncertain transcription span
            if flag_uncertain:
                flag_uncertain = False
                last_end_uncertain = original_line
            else:   ## Again, this should not happen! (but might because of transcription errors)
                error = "ERROR!  End of uncertain transcription span detected twice in a row:  No opening double parentheses for line %s." % original_line
                errorhandler(error)
        else:  ## process words
            if flag_uncertain:
                newwords.append("((" + word + "))")
            else:
                newwords.append(word)

    return (newwords, flag_uncertain, last_beg_uncertain, last_end_uncertain)


## This function originally is from Jiahong Yuan's align.py
## (very much modified by Ingrid...)
def prep_mlf(transcription, mlffile, identifier):
    """writes transcription to the master label file for forced alignment"""
    ## INPUT:
    ## list transcription = list of list of (preprocessed) words
    ## string mlffile = name of master label file
    ## string identifier = unique identifier of process/sound file (can't just call everything "tmp")
    ## OUTPUT:
    ## none, but writes master label file to disk
    
    fw = open(mlffile, 'w')
    fw.write('#!MLF!#\n')
    fw.write('"*/tmp' + identifier + '.lab"\n')
    fw.write('sp\n')
    for line in transcription:
        for word in line:
            ## change unclear transcription ("((xxxx))") to noise
            if word == "((xxxx))":
                word = "{NS}"
                global count_unclear
                count_unclear += 1
            ## get rid of parentheses for uncertain transcription
            if uncertain.search(word):
                word = uncertain.sub(r'\1', word)
                global count_uncertain
                count_uncertain += 1
            ## delete initial asterisks
            if word[0] == "*":
                word = word[1:]
            ## check again that word is in CMU dictionary because of "noprompt" option,
            ## or because the user might select "skip" in interactive prompt
            if word in cmudict:
                fw.write(word + '\n')
                fw.write('sp\n')
                global count_words
                count_words += 1
            else:
                print "\tWarning!  Word %s not in CMU dict!!!" % word.encode('ascii', 'replace')
    fw.write('.\n')
    fw.close()


## This function is from Jiahong Yuan's align.py
## (but adapted so that we're forcing a SR of 16,000 Hz; mono)
def prep_wav(orig_wav, out_wav, SOXPATH=''):
    """adjusts sampling rate  and number of channels of sound file to 16,000 Hz, mono."""

## NOTE:  the wave.py module may cause problems, so we'll just copy the file to 16,000 Hz mono no matter what the original file format!
##    f = wave.open(orig_wav, 'r')
##    SR = f.getframerate()
##    channels = f.getnchannels()
##    f.close()
##    if not (SR == 16000 and channels == 1):  ## this is changed
    SR = 16000
##        #SR = 11025
    if SOXPATH:  ## if FAAValign is used as a CGI script, the path to SoX needs to be specified explicitly
        os.system(SOXPATH + ' \"' + orig_wav + '\" -c 1 -r 16000 ' + out_wav)
    else:        ## otherwise, rely on the shell to find the correct path
        os.system("sox" + ' \"' + orig_wav + '\" -c 1 -r 16000 ' + out_wav)            
        #os.system("sox " + orig_wav + " -c 1 -r 11025 " + out_wav + " polyphase")
##    else:
##        os.system("cp -f " + '\"' + orig_wav + '\"' + " " + out_wav)

    return SR


def process_style_tier(entries, style_tier=None):
    """processes entries of style tier"""
    
    ## create new tier for style, if not already in existence
    if not style_tier:
        style_tier = praat.IntervalTier(name="style", xmin=0, xmax=0)
        if options.verbose:
            print "Processing style tier."
    ## add new interval on style tier
    beg = round(float(entries[2]), 3)
    end = round(float(entries[3]), 3)
    text = entries[4].strip().upper()
    ## check that entry on style tier has one of the allowed values
##    if text in STYLE_ENTRIES:
    style_tier.append(praat.Interval(beg, end, text))
##    else:
##        error = "ERROR!  Invalid entry on style tier:  %s (interval %.2f - %.2f)" % (text, beg, end)
##        errorhandler(error)
        
    return style_tier


def prompt_user(word, clue=''):
    """asks the user for the Arpabet transcription of a word"""
    ## INPUT:
    ## string word = word to be transcribed
    ## string clue = following word (optional)
    ## OUTPUT:
    ## list checked_trans = transcription in Arpabet format (list of phones)
    
    print "Please enter the Arpabet transcription of word %s, or enter [s] to skip." % word
    if clue:
        print "(Following word is %s.)" % clue
    print "\n"
    trans = raw_input()
    if trans != "s":
        checked_trans = check_transcription(trans)
        return checked_trans
    else:
        return None


## This function is from Keelan Evanini's cmu.py:
def read_dict(f):
    """reads the CMU dictionary (or any other dictionary in the same format) and returns it as dictionary object,
    allowing multiple pronunciations for the same word"""
    ## INPUT:  string f = name/path of dictionary file
    ## OUTPUT:  dict cmudict = dictionary of word - (list of) transcription(s) pairs
    ## (where each transcription consists of a list of phones)
    
    dictfile = open(f, 'rU')
    lines = dictfile.readlines()
    cmudict = {}
    pat = re.compile('  *')                ## two spaces separating CMU dict entries
    for line in lines:
        line = line.rstrip()
        line = re.sub(pat, ' ', line)      ## reduce all spaces to one
        word = line.split(' ')[0]          ## orthographic transcription
        phones = line.split(' ')[1:]       ## phonemic transcription
        if word not in cmudict:
            cmudict[word] = [phones]       ## phonemic transcriptions represented as list of lists of phones
        else:
            if phones not in cmudict[word]:
                cmudict[word].append(phones)   ## add alternative pronunciation to list of pronunciations
    dictfile.close()
    
    ## check that cmudict has entries
    if len(cmudict) == 0:
        print "WARNING!  Dictionary is empty."
    if options.verbose:
        print "Read dictionary from file %s." % f
        
    return cmudict


def read_transcription_file(trsfile):
    """reads the transcription file in either ASCII or UTF-16 encoding, returns a list of lines in the file"""

    try:  ## try UTF-16 encoding first
        t = codecs.open(trsfile, 'rU', encoding='utf-16')
        print "Encoding is UTF-16!"
        lines = t.readlines()
    except UnicodeError:
        try:  ## then UTF-8...
            t = codecs.open(trsfile, 'rU', encoding='utf-8')
            print "Encoding is UTF-8!"
            lines = t.readlines()
            lines = replace_smart_quotes(lines)
        except UnicodeError:
            try:  ## then Windows encoding...
                t = codecs.open(trsfile, 'rU', encoding='windows-1252')
                print "Encoding is Windows-1252!"
                lines = t.readlines()
            except UnicodeError:
                t = open(trsfile, 'rU')
                print "Encoding is ASCII!"
                lines = t.readlines()

    return lines


def reinsert_uncertain(tg, text):
    """compares the original transcription with the word tier of a TextGrid and
    re-inserts markup for uncertain and unclear transcriptions"""
    ## INPUT:
    ## praat.TextGrid tg = TextGrid that was output by the forced aligner for this "chunk"
    ## list text = list of words that should correspond to entries on word tier of tg (original transcription WITH parentheses, asterisks etc.)
    ## OUTPUT:
    ## praat.TextGrid tg = TextGrid with original uncertain and unclear transcriptions

    ## forced alignment may or may not insert "sp" intervals between words
    ## -> make an index of "real" words and their index on the word tier of the TextGrid first
    tgwords = []
    for (n, interval) in enumerate(tg[1]):  ## word tier
        if interval.mark() not in ["sp", "SP"]:
            tgwords.append((interval.mark(), n))
##    print "\t\ttgwords:  ", tgwords
##    print "\t\ttext:  ", text

    ## for all "real" (non-"sp") words in transcription:
    for (n, entry) in enumerate(tgwords):
        tgword = entry[0]               ## interval entry on word tier of FA output TextGrid
        tgposition = entry[1]           ## corresponding position of that word in the TextGrid tier
        
        ## if "noprompt" option is selected, or if the user chooses the "skip" option in the interactive prompt,
        ## forced alignment ignores unknown words & indexes will not match!
        ## -> count how many words have been ignored up to here and adjust n accordingly (n = n + ignored)
        i = 0
        while i <= n:
            ## (automatically generated "in'" entries will be in dict file by now,
            ## so only need to strip original word of uncertainty parentheses and asterisks)
            if (uncertain.sub(r'\1', text[i]).lstrip('*') not in cmudict and text[i] != "((xxxx))"):
                n += 1  ## !!! adjust n for every ignored word that is found !!!
            i += 1
        
        ## original transcription contains unclear transcription:
        if text[n] == "((xxxx))":
            ## corresponding interval in TextGrid must have "{NS}"
            if tgword == "{NS}" and tg[1][tgposition].mark() == "{NS}":
                tg[1][tgposition].change_text(text[n])
            else:  ## This should not happen!
                error = "ERROR!  Something went wrong in the substitution of unclear transcriptions for the forced alignment!"
                errorhandler(error)

        ## original transcription contains uncertain transcription:
        elif uncertain.search(text[n]):
            ## corresponding interval in TextGrid must have transcription without parentheses (and, if applicable, without asterisk)
            if tgword == uncertain.sub(r'\1', text[n]).lstrip('*') and tg[1][tgposition].mark() == uncertain.sub(r'\1', text[n]).lstrip('*'):
                tg[1][tgposition].change_text(text[n])
            else:  ## This should not happen!
                error = "ERROR!  Something went wrong in the substitution of uncertain transcriptions for the forced alignment!"
                errorhandler(error)

        ## original transcription was asterisked word
        elif text[n][0] == "*":
            ## corresponding interval in TextGrid must have transcription without the asterisk
            if tgword == text[n].lstrip('*') and tg[1][tgposition].mark() == text[n].lstrip('*'):
                tg[1][tgposition].change_text(text[n])
            else:  ## This should not happen!
                 error = "ERROR!  Something went wrong in the substitution of asterisked transcriptions for the forced alignment!"
                 errorhandler(error)
            
    return tg


# def remove_tempdir(tempdir):
#     """removes the temporary directory and all its contents"""
    
#     for item in os.listdir(tempdir):
#         os.remove(os.path.join(tempdir, item))
#     os.removedirs(tempdir)
#     os.remove("blubbeldiblubb.txt")

 
def replace_extension(filename, newextension):
    """chops off the extension from the filename and replaces it with newextension"""

    return os.path.splitext(filename)[0] + newextension


# def empty_tempdir(tempdir):
#     """empties the temporary directory of all files"""
#     ## (NOTE:  This is a modified version of remove_tempdir)
    
#     for item in os.listdir(tempdir):
#         os.remove(os.path.join(tempdir, item))
#     os.remove("blubbeldiblubb.txt")


def tidyup(tg, beg, end, tgfile):
    """extends the duration of a TextGrid and all its tiers from beg to end;
    inserts empty/"SP" intervals; checks for overlapping intervals"""
    
    ## set overall duration of main TextGrid
    tg.change_times(beg, end)
    ## set duration of all tiers and check for overlaps
    overlaps = []
    for t in tg:
        ## set duration of tier from 0 to overall duration of main sound file
        t.extend(beg, end)
        ## insert entries for empty intervals between existing intervals
        oops = t.tidyup()
        if len(oops) != 0:
            for oo in oops:
                overlaps.append(oo)
        if options.verbose:
            print "Finished tidying up %s." % t
    ## write errorlog if overlapping intervals detected
    if len(overlaps) != 0:
        print "WARNING!  Overlapping intervals detected!"
        write_errorlog(overlaps, tgfile)
        
    return tg


def write_dict(f, dictionary="cmudict", mode='w'):
    """writes the new version of the CMU dictionary (or any other dictionary) to file"""
    
    ## default functionality is to write the CMU pronunciation dictionary back to file,
    ## but other dictionaries or parts of dictionaries can also be written/appended
    if dictionary == "cmudict":
        dictionary = cmudict
#        print "dictionary is cmudict"
    out = open(f, mode)
    ## sort dictionary before writing to file
    s = dictionary.keys()
    s.sort()
    for w in s:
        ## make a separate entry for each pronunciation in case of alternative entries
        for t in dictionary[w]:
            if t:
                out.write(w + '  ')     ## two spaces separating CMU dict entries from phonetic transcriptions
                for p in t:
                    out.write(p + ' ')  ## list of phones, separated by spaces
                out.write('\n')         ## end of entry line
    out.close()
#    if options.verbose:
#        print "Written pronunciation dictionary to file."
   

def write_errorlog(overlaps, tgfile):
    """writes log file with details on overlapping interval boundaries to file"""
    
    ## write log file for overlapping intervals from FA
    logname = os.path.splitext(tgfile)[0] + ".errorlog"
    errorlog = open(logname, 'w')
    errorlog.write("Overlapping intervals in file %s:  \n" % tgfile)
    for o in overlaps:
        errorlog.write("Interval %s and interval %s on tier %s.\n" % (o[0], o[1], o[2]))
    errorlog.close()
    print "Error messages saved to file %s." % logname


def write_alignment_errors_to_log(tgfile, failed_alignment):
    """appends the list of alignment failures to the error log"""

    ## warn user that alignment failed for some parts of the TextGrid
    print "WARNING!  Alignment failed for some annotation units!"

    logname = os.path.splitext(tgfile)[0] + ".errorlog"
    ## check whether errorlog file exists
    if os.path.exists(logname) and os.path.isfile(logname):
        errorlog = open(logname, 'a')
        errorlog.write('\n')
    else:
        errorlog = open(logname, 'w')
    errorlog.write("Alignment failed for the following annotation units:  \n")
    errorlog.write("#\tbeginning\tend\tspeaker\ttext\n")
    for f in failed_alignment:
#        try:
        errorlog.write('\t'.join(f).encode('ascii', 'replace'))
#        except UnicodeDecodeError:
#            errorlog.write('\t'.join(f))
        errorlog.write('\n')
    errorlog.close()
    print "Alignment errors saved to file %s." % logname
    

def write_log(filename, wavfile, duration):
    """writes a log file on alignment statistics"""
    
    f = open(filename, 'w')
    t_stamp = time.asctime()
    f.write(t_stamp)
    f.write("\n\n")
    f.write("Alignment statistics for file %s:\n\n" % os.path.basename(wavfile))

    try:
        check_version = subprocess.Popen(["git","describe", "--tags"], stdout = subprocess.PIPE)
        version,err = check_version.communicate()
        version = version.rstrip()
    except OSError:
        version = None

    if version:
        f.write("version info from Git: %s"%version)
        f.write("\n")
    else:
        f.write("Not using Git version control. Version info unavailable.\n")
        f.write("Consider installing Git (http://git-scm.com/).\
         and cloning this repository from GitHub with: \n \
         git clone git@github.com:JoFrhwld/FAVE.git")
        f.write("\n")

    try:
        check_changes = subprocess.Popen(["git", "diff", "--stat"], stdout = subprocess.PIPE)
        changes, err = check_changes.communicate()
    except OSError:
        changes = None

    if changes:
        f.write("Uncommitted changes when run:\n")
        f.write(changes)
        
    f.write("\n")
    f.write("Total number of words:\t\t\t%i\n" % count_words)
    f.write("Uncertain transcriptions:\t\t%i\t(%.1f%%)\n" % (count_uncertain, float(count_uncertain)/float(count_words)*100))
    f.write("Unclear passages:\t\t\t%i\t(%.1f%%)\n" % (count_unclear, float(count_unclear)/float(count_words)*100))
    f.write("\n")
    f.write("Number of breath groups aligned:\t%i\n" % count_chunks)
    f.write("Duration of sound file:\t\t\t%.3f seconds\n" % duration)
    f.write("Total time for alignment:\t\t%.2f seconds\n" % (times[-1][2] - times[1][2]))
    f.write("Total time since beginning of program:\t%.2f seconds\n\n" % (times[-1][2] - times[0][2]))
    f.write("->\taverage alignment duration:\t%.3f seconds per breath group\n" % ((times[-1][2] - times[1][2])/count_chunks))
    f.write("->\talignment rate:\t\t\t%.3f times real time\n" % ((times[-1][2] - times[0][2])/duration))
    f.write("\n\n")
    f.write("Alignment statistics:\n\n")
    f.write("Chunk\tCPU time\treal time\td(CPU)\td(time)\n")
    for i in range(len(times)):
        ## first entry in "times" tuple is string already, or integer
        f.write(str(times[i][0]))                               ## chunk number
        f.write("\t")
        f.write(str(round(times[i][1], 3)))                     ## CPU time
        f.write("\t")
        f.write(time.asctime(time.localtime(times[i][2])))      ## real time
        f.write("\t")        
        if i > 0:                                               ## time differences (in seconds)
            f.write(str(round(times[i][1] - times[i-1][1], 3)))
            f.write("\t")
            f.write(str(round(times[i][2] - times[i-1][2], 3)))
        f.write("\n")
    f.close()

    return t_stamp


def write_unknown_words(unknown):
    """writes the list of unknown words to file"""
        ## try ASCII output first:
    try:
        out = open(options.check, 'w')
        write_words(out, unknown)
    except UnicodeEncodeError:  ## encountered some non-ASCII characters
        out = codecs.open(options.check, 'w', 'utf-16')
        write_words(out, unknown)


def write_words(out, unknown):
    """writes unknown words to file (in a specified encoding)"""

    for w in unknown:
        out.write(w)
        if unknown[w]:
            out.write('\t')
            ## put suggested transcription(s) for truncated word into second column, if present:
            if unknown[w][0]:
                 out.write(','.join([' '.join(i) for i in unknown[w][0]]))
            out.write('\t')
            ## put following clue word in third column, if present:
            if unknown[w][1]:
                out.write(unknown[w][1])
            ## put line in fourth column:
            out.write('\t' + unknown[w][2])
        out.write('\n')
    out.close()



################################################################################
## This used to be the main program...                                        ##
## Now it's wrapped in a function so we can import the code                   ##
## without supplying the options and arguments via the command line           ##
################################################################################


def FAAValign(opts, args, FADIR='', SOXPATH=''):
    """runs the forced aligner for the arguments given"""

    tempdir = os.path.join(FADIR, TEMPDIR)

    ## need to make options global (now this is no longer the main program...)
    global options
    options = opts

    ## get start time of program
    global times
    times = []
    mark_time("start")
    
    ## positional arguments should be soundfile, transcription file, and TextGrid file
    ## (checking that the options are valid is handled by the parser)
    (wavfile, trsfile, tgfile) = check_arguments(args)
    ## (returned values are the full paths!)
    
    ## read CMU dictionary
    ## (default location is "/model/dict", unless specified otherwise via the "--dict" option)
    global cmudict
    cmudict = read_dict(os.path.join(FADIR, options.dict))
 
    ## add transcriptions from import file to dictionary, if applicable
    if options.importfile:
        add_dictionary_entries(options.importfile, FADIR)
            
    ## read transcription file
    all_input = read_transcription_file(trsfile)
    if options.verbose:
        print "Read transcription file %s." % os.path.basename(trsfile)

    ## initialize counters
    global count_chunks
    global count_words
    global count_uncertain
    global count_unclear
    global style_tier
        
    count_chunks = 0
    count_words = 0
    count_uncertain = 0
    count_unclear = 0
    style_tier = None
    failed_alignment = []

    HTKTOOLSPATH = options.htktoolspath

    ## check correct format of input file; get list of transcription lines
    ## (this function skips empty annotation units -> lines to be deleted)
    if options.verbose:  
        print "Checking format of input transcription file..."
    trans_lines, delete_lines = check_transcription_file(all_input)

    ## check that all words in the transcription columen of trsfile are in the CMU dictionary
    ## -> get list of words for each line, preprocessed and without "clue words"
    ## NOTE:    If the "check transcription" option is selected,
    ##          the list of unknown words will be output to file
    ##          -> END OF PROGRAM!!!
    if options.verbose:  
        print "Checking dictionary entries for all words in the input transcription..."
    trans_lines = check_dictionary_entries(trans_lines, wavfile)
    if not trans_lines and not __name__ == "__main__":
        return

    ## make temporary directory for sound "chunks" and output of FA program
    #make_tempdir(tempdir)
    check_tempdir(tempdir)
    #if options.verbose:  
    #    print "Checked temporary directory %s." % tempdir

    ## generate main TextGrid and get overall duration of main sound file
    main_textgrid = praat.TextGrid()
    if options.verbose:  
        print "Generated main TextGrid."
    duration = get_duration(wavfile, FADIR)
    if options.verbose:  
        print "Duration of sound file:  %f seconds." % duration

    ## delete empty lines from array of original transcription lines
    all_input2 = delete_empty_lines(delete_lines, all_input)
    ## check length of data arrays before zipping them:
    if not (len(trans_lines) == len(all_input)):
        error = "ERROR!  Length of input data lines (%s) does not match length of transcription lines (%s).  Please delete empty transcription intervals." % (len(all_input), len(trans_lines))
        errorhandler(error)

    mark_time("prelim")

    ## start alignment of breathgroups
    for (text, line) in zip(trans_lines, all_input):

        entries = line.strip().split('\t')
        ## start counting chunks (as part of the output file names) at 1
        count_chunks += 1

        ## style tier?
        if (entries[0] in STYLE) or (entries[1] in STYLE):
            style_tier = process_style_tier(entries, style_tier)
            continue

        ## normal tiers:
        speaker = entries[1].strip().encode('ascii', 'ignore').replace('/', ' ')  ## eventually replace all \W!
        if not speaker:  ## some people forget to enter the speaker name into the second field, try the first one (speaker ID) instead
            speaker = entries[0].strip()
        beg = round(float(entries[2]), 3)
        end = min(round(float(entries[3]), 3), duration)  ## some weird input files have the last interval exceed the duration of the sound file
        dur = round(end - beg, 3)
        if options.verbose:
            try:
                print "Processing %s -- chunk %i:  %s" % (speaker, count_chunks, " ".join(text))
            except (UnicodeDecodeError, UnicodeEncodeError):  ## I will never get these encoding issues...  %-(
                print "Processing %s -- chunk %i:  %s" % (speaker, count_chunks, " ".join(text).encode('ascii', 'replace'))

        if dur < 0.05:
            print "\tWARNING!  Annotation unit too short (%s s) - no alignment possible." % dur
            print "\tSkipping alignment for annotation unit ", " ".join(text).encode('ascii', 'replace')
            continue
            
        ## call SoX to cut the corresponding chunk out of the sound file
        chunkname_sound = "_".join([os.path.splitext(os.path.basename(wavfile))[0], speaker.replace(" ", "_"), "chunk", str(count_chunks)]) + ".wav"
        cut_chunk(wavfile, os.path.join(tempdir, chunkname_sound), beg, dur, SOXPATH)
        ## generate name for output TextGrid
        chunkname_textgrid = os.path.splitext(chunkname_sound)[0] + ".TextGrid"
                    
        ## align chunk
        try:
            align(os.path.join(tempdir, chunkname_sound), [text], os.path.join(tempdir, chunkname_textgrid), FADIR, SOXPATH, HTKTOOLSPATH)
        except Exception, e:
            try:
                print "\tERROR!  Alignment failed for chunk %i (speaker %s, text %s)." % (count_chunks, speaker, " ".join(text))
            except (UnicodeDecodeError, UnicodeEncodeError): 
                print "\tERROR!  Alignment failed for chunk %i (speaker %s, text %s)." % (count_chunks, speaker, " ".join(text).encode('ascii', 'replace'))
            print "\n", traceback.format_exc(), "\n"
            print "\tContinuing alignment..."
            failed_alignment.append([str(count_chunks), str(beg), str(end), speaker, " ".join(text)])
            ## remove temp files
            os.remove(os.path.join(tempdir, chunkname_sound))
            os.remove(os.path.join(tempdir, chunkname_textgrid))
            continue
           
        ## read TextGrid output of forced alignment
        new_textgrid = praat.TextGrid()
        new_textgrid.read(os.path.join(tempdir, chunkname_textgrid))
        ## re-insert uncertain and unclear transcriptions
        new_textgrid = reinsert_uncertain(new_textgrid, text)
        ## change time offset of chunk
        new_textgrid.change_offset(beg)
        if options.verbose:
            print "\tOffset changed by %s seconds." % beg

        ## add TextGrid for new chunk to main TextGrid
        main_textgrid = merge_textgrids(main_textgrid, new_textgrid, speaker, chunkname_textgrid)

        ## remove sound "chunk" and TextGrid from tempdir
        os.remove(os.path.join(tempdir, chunkname_sound))
        os.remove(os.path.join(tempdir, chunkname_textgrid))
        
        mark_time(str(count_chunks))
        
    ## add style tier to main TextGrid, if applicable
    if style_tier:
        main_textgrid.append(style_tier)

    ## tidy up main TextGrid (extend durations, insert empty intervals etc.)
    main_textgrid = tidyup(main_textgrid, 0, duration, tgfile)

    ## append information on alignment failure to errorlog file
    if failed_alignment:
        write_alignment_errors_to_log(tgfile, failed_alignment)

    ## write main TextGrid to file
    main_textgrid.write(tgfile)
    if options.verbose:
        print "Successfully written TextGrid %s to file." % os.path.basename(tgfile)

    ## delete temporary transcription files and "chunk" sound file/temp directory
    #remove_tempdir(tempdir)
    #empty_tempdir(tempdir)
    #os.remove("blubbeldiblubb.txt")
    ## NOTE:  no longer needed because sound chunks and corresponding TextGrids are cleaned up in the loop
    ##        also, might delete sound chunks from other processes running in parallel!!!

    ## remove temporary CMU dictionary
    os.remove(temp_dict)
    if options.verbose:
        print "Deleted temporary copy of the CMU dictionary."
    
    ## write log file
    t_stamp = write_log(os.path.splitext(wavfile)[0] + ".FAAVlog", wavfile, duration)
    if options.verbose:
        print "Written log file %s." % os.path.basename(os.path.splitext(wavfile)[0] + ".FAAVlog")


################################################################################
## MAIN PROGRAM STARTS HERE                                                   ##
################################################################################

if __name__ == '__main__':
        
    ## get input/output file names and options
    parser = define_options_and_arguments()
    (opts, args) = parser.parse_args()

    FAAValign(opts, args)



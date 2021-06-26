# Installation notes for Amazon Linux on AWS

The issues encountered and how to create an EC2 instance with static binaries. This should support the Lambda functionality of AWS but is untested.

## Dependencies

Below are the build dependencies for FAVE-align to run on Amazon Linux.

### Required for MVP (minimum viable product)

Each of the below are compiled as static binaries where compilation is necessary and are compiled as 64-bit applications.
All dependencies are listed including those that can be installed from packages.

 - SoX
    - libmad
    - lame
 - HTK with HDecode
 - Praat
 - Python 2.7.x
 - FAVE-align custom wrapper for ease of use

### Optional

The following are useful extras that we will be installing.

 - Python NumPy for unused FAVE-extract functionality
 - PuDB Python Debugger - local console debugging
    - Installation and simple usage document
 - PyCharm Professional - remote gui debugging
    - Configuration of a remote server debugging and remote deployment to AWS EC2.

## Amazon Linux Platform

Amazon Linux does not support HTK, SoX, or Praat as a package. Manual build processes have been done for the platform. Packaging is an overhead that we will avoid at this time.

### Static Build

All binaries are compiled with their libraries and dependencies stored with the binary. This makes them portable between environments. This makes AWS Lambda execution a possibility.

### 64-bit Build
Built all the utilities and libraries in 64-bit mode to best take advantage of the environment and reduce complexity and overhead with multi-platform binaries. This also makes execution in the Lambda environment theoretically easier.

### Server Build
 - HTK
    - Removed ???
 - Praat
    - Removed additional functionality that is not necessary for a command line or server execution. No user interface is presented which reduces the overhead.

## AWS Lambda

Future endeavors will include instigation of a serverless architecture for a web site like the UPenn FAVE that is no longer in service.
The AWS Lambda could bring down the costs and increase the CPU effectiveness per execution of FAVE-align.

Additionally, AWS Cognito and AWS SES could be leveraged to provide authentication and Email services.

The AWS S3 service is purpose built as an object data store which could house the content for the users.


## PyCharm Debug Configurations

```
Name:               en_US help
Script:             ${HOME}/PycharmProjects/FAVE/FAVE-align/FAAValign.py
Script Parameters:  --help
Working Directory:  /Users/jamesmcgarrah/PycharmProjects/FAVE/FAVE-align
```


```
Name:               sv_SE gen_test
Script:             ${HOME}/PycharmProjects/FAVE/FAVE-align/FAAValign.py
Script Parameters:  -v -l sv_SE ${HOME}/PycharmProjects/FAVE/FAVE-align/examples/sv_SE/gen_test/sv_SE_test.wav ${HOME}/PycharmProjects/FAVE/FAVE-align/examples/sv_SE/gen_test/sv_SE_test.txt
Working Directory:  /Users/jamesmcgarrah/PycharmProjects/FAVE/FAVE-align
```

```
Name:               sv_SE long_test
Script:             ${HOME}/PycharmProjects/FAVE/FAVE-align/FAAValign.py
Script Parameters:  -v -l sv_SE ${HOME}/PycharmProjects/FAVE/FAVE-align/examples/sv_SE/gen_test/sv_SE_longtest.wav ${HOME}/PycharmProjects/FAVE/FAVE-align/examples/sv_SE/gen_test/sv_SE_longtest.txt
Working Directory:  /Users/jamesmcgarrah/PycharmProjects/FAVE/FAVE-align
```

PyCharm MacOS - Bug Report - Issue with Working Directory not taking a variable.
https://intellij-support.jetbrains.com/hc/en-us/requests/1108277
The work around is to hard code the User Home path.

## MacOS (Sierra) Installation

### IDE Environment and Git

Installed PyCharm Professional for MacOS. Checkout the code from Git Repository for private FAVE repo.

### First run

Attempt to run FAVE-Align
```
$ cd PycharmProjects/FAVE/
$ ls
FAVE-align	FAVE-extract	LICENSE		NEWS.md		README.md
$ cd FAVE-align/
$ ls
DanFAAValign.py		README.md		model
EngFAAValign.py		SweFAAValign.py		old_docs
FAAValign.py		added_dict_entries.txt	praat.py
GENERALIZED.md		examples		readme_img
INSTALL.md		get_duration.praat	tg_unicode_test.py
$ python FAAValign.py --help
Usage: (python) FAAValign.py [options] soundfile.wav [transcription.txt] [output.TextGrid]    

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
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -c FILENAME, --check=FILENAME
                        Checks whether phonetic transcriptions for all words
                        in the transcription file can be found in the CMU
                        Pronouncing Dictionary.  Returns a list of unknown
                        words (required argument "FILENAME").
  -i FILENAME, --import=FILENAME
                        Adds a list of unknown words and their corresponding
                        phonetic transcriptions to the CMU Pronouncing
                        Dictionary prior to alignment.  User will be prompted
                        interactively for the transcriptions of any remaining
                        unknown words.  Required argument "FILENAME" must be
                        tab-separated plain text file (one word - phonetic
                        transcription pair per line).
  -v, --verbose         Detailed output on status of dictionary check and
                        alignment progress.
  -d FILENAME, --dict=FILENAME
                        Specifies the name of the file containing the
                        pronunciation dictionary.  Default file is
                        "/model/dict".
  -l LANG_ID, --lang=LANG_ID
                        Specifies the locale id of the language definition.
                        Default locale id is "en_US".
  -n, --noprompt        User is not prompted for the transcription of words
                        not in the dictionary, or truncated words.  Unknown
                        words are ignored by the aligner.
  -t HTKTOOLSPATH, --htktoolspath=HTKTOOLSPATH
                        Specifies the path to the HTKTools directory where the
                        HTK executable files are located.  If not specified,
                        the user's path will be searched for the location of
                        the executable.

The following additional programs need to be installed and in the path:
- Praat (on Windows machines, the command line version praatcon.exe)
- SoX
MacBook-Pro-2:FAVE-align jamesmcgarrah$ python FAAValign.py ./examples/en_US/gen_test/en_US_Testing.wav ./examples/en_US/gen_test/en_US_Testing.txt 
Encoding is UTF-16!
Encoding is UTF-8!
temp_dict is ./examples/en_US/gen_test/en_US_dict.
sh: sox: command not found
sh: sox: command not found
sh: HCopy: command not found
sh: HVite: command not found
	ERROR!  Alignment failed for chunk 1 (speaker Nate, text TESTING ONE TWO).

Traceback (most recent call last):
  File "FAAValign.py", line 1750, in FAAValign
    align(os.path.join(tempdir, chunkname_sound), [text], os.path.join(tempdir, chunkname_textgrid), FADIR, SOXPATH, HTKTOOLSPATH)
  File "FAAValign.py", line 230, in align
    raise Exception, FA_error
Exception: Error in aligning file en_US_Testing_Nate_chunk_1.wav:  [Errno 2] No such file or directory: u'./tmpenUSTestingNate1/alignedenUSTestingNate1.mlf'.

	Continuing alignment...
Traceback (most recent call last):
  File "FAAValign.py", line 1833, in <module>
    FAAValign(opts, args)
  File "FAAValign.py", line 1760, in FAAValign
    os.remove(os.path.join(tempdir, chunkname_sound))
OSError: [Errno 2] No such file or directory: 'en_US_Testing_Nate_chunk_1.wav'
MacBook-Pro-2:FAVE-align jamesmcgarrah$ sox
-bash: sox: command not found
MacBook-Pro-2:FAVE-align jamesmcgarrah$ HCopy
-bash: HCopy: command not found
```

Outcome is that we need Praat, HTK and SoX installed.

### Install Homebrew

```
https://brew.sh/
$ /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
```

#### Install Praat

Praat is available pre-built with the GUI included. We also have a linux build 
that excludes all the GUI/X11 for a webserver based version that could also be
locally built on MacOS.

```
$ brew cask install praat
==> Tapping caskroom/cask
Cloning into '/usr/local/Homebrew/Library/Taps/caskroom/homebrew-cask'...
remote: Counting objects: 3851, done.
remote: Compressing objects: 100% (3835/3835), done.
remote: Total 3851 (delta 30), reused 543 (delta 12), pack-reused 0
Receiving objects: 100% (3851/3851), 1.31 MiB | 6.98 MiB/s, done.
Resolving deltas: 100% (30/30), done.
Tapped 0 formulae (3,860 files, 4.1MB)
==> Creating Caskroom at /usr/local/Caskroom
==> We'll set permissions properly so we won't need sudo in the future
Password:
==> Satisfying dependencies
==> Downloading https://github.com/praat/praat/releases/download/v6.0.32/praat60
######################################################################## 100.0%
==> Verifying checksum for Cask praat
==> Installing Cask praat
==> Moving App 'Praat.app' to '/Applications/Praat.app'.
==> Linking Binary 'Praat' to '/usr/local/bin/praat'.
🍺  praat was successfully installed!
```

#### SoX audio tool Installation

The sound/audio tool can also me installed from Brew. A static version could be built
as well using the Linux built notes.

```
$ brew install sox
==> Installing dependencies for sox: libpng, mad
==> Installing sox dependency: libpng
==> Downloading https://homebrew.bintray.com/bottles/libpng-1.6.34.sierra.bottle
######################################################################## 100.0%
==> Pouring libpng-1.6.34.sierra.bottle.tar.gz
🍺  /usr/local/Cellar/libpng/1.6.34: 26 files, 1.2MB
==> Installing sox dependency: mad
==> Downloading https://homebrew.bintray.com/bottles/mad-0.15.1b.sierra.bottle.1
######################################################################## 100.0%
==> Pouring mad-0.15.1b.sierra.bottle.1.tar.gz
🍺  /usr/local/Cellar/mad/0.15.1b: 12 files, 320KB
==> Installing sox
==> Downloading https://homebrew.bintray.com/bottles/sox-14.4.2.sierra.bottle.ta
######################################################################## 100.0%
==> Pouring sox-14.4.2.sierra.bottle.tar.gz
🍺  /usr/local/Cellar/sox/14.4.2: 22 files, 1.7MB
```

#### HTK Toolkit Build 

There is no pre-built version of HTK available. This built processes has been tested on
a MacBook Pro mid 2012 with 16GB RAM on MacOS Sierra 10.12.6.

##### HTK Build Process

Install a pre-req for the build process.
```
$ brew install autoconf
```

Create a directory for the HTK build
```
$ cd $HOME
$ mkdir htk
$ cd htk
```

Get an extract the HTK source code. Please do not share my password.
```
$ wget --user=<USERNAME> --password=<PASSWORD> http://htk.eng.cam.ac.uk/ftp/software/HTK-3.4.1.tar.gz
$ wget --user=<USERNAME> --password=<PASSWORD> http://htk.eng.cam.ac.uk/ftp/software/HTK-samples-3.4.1.tar.gz
$ wget --user=<USERNAME> --password=<PASSWORD> http://htk.eng.cam.ac.uk/ftp/software/hdecode/HDecode-3.4.1.tar.gz

tar zxf HTK-3.4.1.tar.gz
tar zxf HTK-samples-3.4.1.tar.gz
tar zxf HDecode-3.4.1.tar.gz
```

Update the Autoconf/Configure script to support MacOS 64-bit.
```
pushd htk
sed -i.bak -e '145,154H;155{;x;s/^\n//;p;x;}; 145s/i386/x86_64/' configure.ac
autoconf
popd
```

Fix the issue in the HRec.c file.
```
pushd htk/HTKLib
sed -i.bak '1650s/ labid / labpr /' HRec.c
popd
```

Configure, Build and Install the HTK software
```
$ pushd htk
$ ./configure --without-x --disable-hslab --disable-hlmtools --build=x86_64-apple-darwin --disable-multilib
$ make all
$ sudo make install
$ make hdecode
$ sudo make install-hdecode
$ popd
```

Check that the individual components installed above are accessible to FAVE.
```
$ sox --version
sox:      SoX v
$ praat --version
Praat 6.0.32 (September 16 2017)
$ which HCopy
/usr/local/bin/HCopy
```

Execute FAVE-Align and verify it now functions.
```
$ cd PycharmProjects/FAVE/FAVE-align
$ python FAAValign.py examples/en_US/gen_test/en_US_
en_US_Testing.FAAVlog   en_US_Testing.txt       en_US_dict
en_US_Testing.TextGrid  en_US_Testing.wav       
MacBook-Pro-2:FAVE-align jamesmcgarrah$ python FAAValign.py examples/en_US/gen_test/en_US_Testing.wav examples/en_US/gen_test/en_US_Testing.txt
Encoding is UTF-16!
Encoding is UTF-8!
temp_dict is examples/en_US/gen_test/en_US_dict.
```

Review and open the resulting TextGrid with the Audio file using Praat.
```
$ cd examples/en_US/gen_test
$ praat --open ./en_US_Testing.TextGrid ./en_US_Testing.wav 
```

High-light both files that are listed and Click the "View and Edit" to display the
combined Phonetic, Transcript and Audio graphs together in one visualization.

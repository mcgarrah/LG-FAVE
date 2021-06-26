# FAVE-align

This is a fork of the FAVE-align to support generalized language features.

## JMM Todo

1. Docker update to status - explain value proposition
1. Fix the `--lang` parameter for early evaluation in `__main__` before `FAAValign()`
1. Update `--lang` load for `model\{lang_id}\{land_id}.py` language import file
1. Website updates for Milestone 2 (PDF limitations)
1. `read_transcription_file()` feeds the following:
  1.  under5 `replace_smart_quotes()`
  1.  under5 `preprocess_transcription()`
1. [StackOverflow for importlib.import_module](https://stackoverflow.com/questions/301134/dynamic-module-import-in-python)

## Generalizations

Add notes on why this is necessary.
Also notes on what has changed from baseline.

## Usage

Changes in usage

## Configuration

Changes in configs will include a language option flag.

`-l <id> | --lang=<id>`

Addition of a IETF language tag (https://en.wikipedia.org/wiki/IETF_language_tag) using the Language-Region subset. 
This could be extended to use the full BCP 47 (https://tools.ietf.org/rfc/bcp/bcp47.txt) as necessitated by language
inclusions.

 | *Locale ID* | *Language* | *Region*      | *Variant*      |
 |:------------|:----------:|:-------------:|:--------------:|
 | `en-US`     | English    | United States | 
 | `sv-SE`     | Swedish    | Sweden        | 
 | `da-DK`     | Danish     | Denmark       | 
 | `sv-SE-me`  | Swedish    | Sweden        | Multiethnolect 
 | `sv-FI`     | Swedish    | Finland       | 
 | `nb-NO`     | Norwegian  | Norway        | 
 | `fr-CA`     | French     | Canada        | 
 | `es-US`     | Spanish    | United States | 
 
 Run 'locale -a' on a linux system to get a comprehensive list of values.
 http://www.science.co.il/language/Locale-codes.php also offers a simplified list based on Microsoft Windows.
 
## Notes
Here are some notes on things to consider for future work. Model buliding in particular.

#### HTK Howto
The MLF formats in the examples directory are important but not investigated beyond they exist. There are not part of
the phase 1 generalization effort.

 * http://ai.stanford.edu/~amaas/data/htkbook.pdf
 * http://htk.eng.cam.ac.uk/prot-docs/htkbook.pdf

#### HARK Cookbook
Here is a link to the MLF and other HTK formatting.
 * http://www.hark.jp/document/1.1.0/hark-cookbook-en/secModels.html
  
  
# References for Markdown

 * https://github.com/adam-p/markdown-here/wiki/Markdown-Cheatsheet
 * https://github.com/adam-p/markdown-here/wiki/Markdown-Here-Cheatsheet
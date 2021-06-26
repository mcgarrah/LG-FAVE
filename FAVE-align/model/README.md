# Generalized Models

Changes have been made to the model directory to support multiple language models. For each language we have a 
sub-directory that contains the models from HTKTool acoustic models, the phonetic dictionary, and any other 
support files for that language.

## Configuration files

The `en_US.py` is the "English - United State" language configuration file. It is the default used by 
the `FAAValign.py` to find the language specific models and dictionaries.

The `se_SV.py` is the "Swedish - Sweden" language configuration file. It must be specified via the `--lang` parameter
to be used. It contains the language specific features like the above but includes a new feature called RULES.
 

## Utilities

`merge_dicts.py` is a stand alone script used to merge dictionary files. It was present earlier and uses the same base
code as the `FAAValign.py` does to merge the parameter provided 'import' and 'dict' dictionaries.

## Versioning

We have chosen the [Semantic Version](http://semver.org) standard with a MAJOR, MINOR and PATCH 
for managing versions of the configuration files.

### Summary

Given a version number MAJOR.MINOR.PATCH, increment the:

1. MAJOR version when you make incompatible API changes,
1. MINOR version when you add functionality in a backwards-compatible manner, and
1. PATCH version when you make backwards-compatible bug fixes.

This allows for adding new features that break compatibility, features that are backwards compatible,
and bug fix releases. With this, we can manage the changes to the language rules in code.
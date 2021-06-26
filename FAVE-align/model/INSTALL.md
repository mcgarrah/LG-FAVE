The language model dictionary files are larger than Github LFS file size limits of 100mb files. So those language model directories are tar and gzip compressed into archives.

They will need to be extracted into this folder.

For UNIX:

tar xvf en_US.tgz

This will extract a folder en_US in the same directory that can be used.

The same process will be needed for each of the TGZ archives for da_DK.tgz and sv_SE.tgz as well.

On Windows or MacOS tools like 7zip or other archive tools that can work on tarballs gzip files can be used as well.

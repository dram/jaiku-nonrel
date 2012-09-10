#!/bin/sh
# Get a nice git checkout of JaikuEngine, great for working with rietku 
# and git-cl.
# Should not be run from inside a jaikuengine checkout
SVN_TRUNK=jaikuengine.googlecode.com/svn/trunk/
READONLY_TRUNK=http://$SVN_TRUNK 
COMMIT_TRUNK=https://$SVN_TRUNK 

until [ -z "$1" ];
do
  if [[ "$1" == "readonly" ]]
  then
    READONLY=1
    COMMIT_TRUNK=$READONLY_TRUNK
  else
    if [ -z "$TARGET_DIR" ]
    then
      TARGET_DIR=$1
    elif [ -z "$EXISTING_DIR" ]
    then
      EXISTING_DIR=$1
    fi
  fi
  shift
done
[ -z "$EXISTING_CHECKOUT" ] && EXISTING_CHECKOUT="jaikuengine-read-only"
[ -z "$TARGET_DIR" ] && TARGET_DIR="jaikuengine-git"


if [ ! -d "$EXISTING_CHECKOUT" ]
then
  svn co $READONLY_TRUNK $EXISTING_CHECKOUT
fi

if [ -d "$TARGET_DIR" ]
then
  echo "Target directory already exists!"
  exit 1;
fi

if [ "$READONLY_TRUNK" != "$COMMIT_TRUNK" ]
then
  echo "################"
  echo "#" 
  echo "# If you do not have commit access, the next command will fail,"
  echo "# you will need to pass 'readonly' as an argument to this file"
  echo "#"
  echo "# e.g. $$ ./jaikuengine-read-only/bin/gitify.sh readonly"
  echo "#"
  echo "################"
fi

git svn clone $COMMIT_TRUNK $TARGET_DIR

# Copy over externals
echo "Checking externals (this takes a little while for some reason)..."
cd $TARGET_DIR
EXTERNALS=`git svn show-externals | grep "^/" | awk '{print $1}'`
for ext in `echo $EXTERNALS`
do
  echo "  Linking $EXISTING_CHECKOUT$ext..."
  ln -s `dirname $PWD`/$EXISTING_CHECKOUT$ext .$ext
  echo "$ext" >> .gitignore
done
echo "Done."

# Set up a basic .gitignore
echo "*.pyc" >> .gitignore
echo "*.swp" >> .gitignore
echo "index.yaml" >> .gitignore
echo ".gitignore" >> .gitignore

# GIFBuild.py by J. M. Skelton


# -----
# Notes
# -----

# A few suggestions for rendering in VMD:

# 1. Set a large display window and enable anti aliasing (using Extensions > Tk Console): display size 1600 1600; display antialias on
# 2. Overlay the unit cell by selecting the molecule in the VMD Main window, then entering: pbc set {a b c alpha beta gamma}; pbc box_draw
# 3. Change a few options in the Display menu: Orthographic projection, Depth Cueing off, Axes > Off
# 4. Change the representations: VDW (Sphere Scale 0.3, Sphere Resolution 25) + Bonds (Bond Radius 0.1, BondResolution 25); Coloring Method: Element, Material: BrushedMetal
# 5. Change the colours (Graphics > Colors...): Element > C > black; Display > Background > white


# ----------
# Parameters
# ----------

# Path to the merged animation XYZ file generated by MolecularCrystalPhononAnimation.py.

MergedXYZFile = r"MolecularCrystal_Animations-Merged.xyz";

# Folder containing the animation frame images.

AnimationFrameImageFolder = r"/path/to/temporary/folder";

# This script expects the image files to be named "<AnimationFramePrefix>.<FileNumber>.<AnimatioNFrameExtension>.
# If this needs to be overridden, modify Section 2 of the Main block below.

AnimationFramePrefix = "MolecularCrystal";
AnimationFrameExtension = ".ppm";

# Background colour used in the animation frames.
# If set to None, this will be inferred from the first image in the sequence.

AnimationFrameBackgroundColour = None;

# Prefix for the output files.

OutputPrefix = "MolecularCrystal";

OverwriteExisting = False;

# If set, print out some timing information from the slower routines in the code.

DebugMode = False;


# -------
# Imports
# -------

import math;
import os;
import re;
import time;

import numpy as np;

import matplotlib as mpl;
import matplotlib.pyplot as plt;

from multiprocessing import Pool;

from matplotlib.gridspec import GridSpec;
from matplotlib.image import imread;

from mpl_toolkits.axes_grid.anchored_artists import AnchoredText;

from scipy.stats import mode;


# ---------
# Constants
# ---------

_XYZCommentLineRegex = re.compile(r"mode =\s+(?P<mode_index>\d+), v =\s+(?P<mode_frequency_thz>-?\d+\.\d+) THz \(\s*(?P<mode_frequency_invcm>-?\d+\.\d+) cm\^-1\), q =\s+(?P<mode_amplitude>-?\d+\.\d+) amu\^1/2 A");

_CaptionedAnimationFrameCaptionHeight = 0.5 / 2.54;

# This works well for square anumation frames with a 0.5 cm caption; although Matplotlib will automatically centre and scale the frames, this may need to be adjusted for frames with significantly different aspect ratios.

_CaptionedAnimationFrameDimensions = (8.0 / 2.54, 8.6 / 2.54);


# ---------
# Functions
# ---------

# Function to read a merged animation XYZ file produced by MolecularCrystalPhononAnimation.py and extract the mode index, frequency (THz/inverse cm) and normal-mode coordinate (amplitude) associated with each frame.

def _ReadMergedXYZFileCommentLines(filePath):
    xyzData = { };

    with open(filePath, 'r') as inputReader:
        for line in inputReader:
            match = _XYZCommentLineRegex.search(line);

            if match:
                modeIndex = int(match.group('mode_index'));
                modeFrequencyTHz = float(match.group('mode_frequency_thz'));
                modeFrequencyInvCm = float(match.group('mode_frequency_invcm'));
                modeAmplitude = float(match.group('mode_amplitude'));

                if modeIndex in xyzData:
                    _, _, modeAmplitudes = xyzData[modeIndex];
                    modeAmplitudes.append(modeAmplitude);
                else:
                    xyzData[modeIndex] = (modeFrequencyTHz, modeFrequencyInvCm, [modeAmplitude]);

    # Sanity check.

    if len(xyzData) == 0:
        raise Exception("Error: No data extracted from input file \"{0}\".".format(filePath));

    return xyzData;

# Function for reading animation frames.
# This is a wrapper around imread() which changes the data type if need be.

def _ReadAnimationFrame(filePath):
    # Read the image with imread().

    image = imread(filePath);

    # The data type of the array returned by imread() depends on the image format.
    # For Matplotlib, we need them in the 'float32' format (pixel colours in the range [0, 1]).

    if image.dtype != np.float32:
        # If the images are not read in this format, the most likely alternative is 'uint8' (8 bpp, pixel colours in the range [0, 255]).

        if image.dtype == np.uint8:
            image = image.astype(dtype = np.float32) / 255.0;
        else:
            raise Exception("Error: _RenderCaptionedAnimationFrame(): Unknown image data type '{0}'.".format(image.dtype));

    return image;

# Function to prepare captioned animation frames for a given mode using animation data prepared by the script.

def _PrepareCaptionedAnimationFrames(modeIndex, animationData, frameColour, fileNamePrefix):
    modeFrequencyTHz, modeFrequencyInvCm, modeAmplitudes, animationFrameImageFiles = animationData;

    # Convert the mode frequency to a string with a sensible number of significant figures.

    modeFrequencyString = None;

    # Make sure zero-frequency acoustic modes don't cause the log to blow up.

    if modeFrequencyInvCm != 0.0:
        power = int(
            math.floor(math.log10(math.fabs(modeFrequencyInvCm)))
            );

        if power < 1:
            modeFrequencyString = "{0:.2f}".format(modeFrequencyInvCm);
        elif power < 2:
            modeFrequencyString = "{0:.1f}".format(modeFrequencyInvCm);
        else:
            modeFrequencyString = "{0:.0f}".format(modeFrequencyInvCm);
    else:
        modeFrequencyString = "0.00";

    # Generate a format string for the mode amplitudes.

    maxAmplitude = max(
        abs(modeAmplitude) for modeAmplitude in modeAmplitudes
        );

    # Sanity check.

    if maxAmplitude == 0.0:
        raise Exception("Error: _PrepareCaptionedAnimationFrames(): Maximum absolute normal-mode amplitude is zero.");

    power = int(
        math.floor(math.log10(math.fabs(maxAmplitude)))
        );

    # In cases where all the amplitudes are < 1, we still need one digit for the integer part.

    power = max(power, 0);

    # If the base power of 10 is x, we need x + 1 characters to display the integer part, plus three for the fractional part and one each for the decimal point and a possible leading sign.

    modeAmplitudeFormatString = "{{0: >{0}.3f}}".format(power + 6);

    # Prepare the animation frames.

    # Record the names of the output frames for further processing.
    # Also record the time taken for debugging purposes.

    startTime = time.time();

    fileNames = [];

    for i, (modeAmplitude, animationFrameImageFile) in enumerate(zip(modeAmplitudes, animationFrameImageFiles)):
        # Generate a caption.

        caption = r"Mode {0}: $\nu$ = {1} cm$^{{-1}}$, $Q$ = {2} amu$^{{\frac{{1}}{{2}}}}$ $\mathrm{{\AA}}$".format(modeIndex, modeFrequencyString, modeAmplitudeFormatString.format(modeAmplitude));

        # Generate a file name.

        fileName = r"{0}_{1}-{2}.png".format(fileNamePrefix, modeIndex, i + 1);

        # Render and save the frame.

        _RenderCaptionedAnimationFrame(animationFrameImageFile, caption, frameColour, fileName);

        # Record the file name of the rendered frame.

        fileNames.append(fileName);

    totalTime = time.time() - startTime;

    # If the DebugMode flag is set, print the time taken for the rendering.

    if DebugMode:
        print("DEBUG: _PrepareCaptionedAnimationFrames(): Rendered {0} frame(s) in {1:.2f} s".format(len(fileNames), totalTime));

    # Return the list of file names.

    return fileNames;

# Function to read in an animation frame and render a captioned frame with Matplotlib.
# This is called from _PrepareCaptionedAnimationFrames(), and was separated in order to a) keep the Matplotlib rendering code separate from the pre processing, and b) to enable possible multithreading in future.

def _RenderCaptionedAnimationFrame(imageFile, caption, frameColour, outputPath):
    # Record the start time for debugging purposes.

    startTime = time.time();

    # Read the image file and record the time taken.

    readStartTime = time.time();

    image = _ReadAnimationFrame(imageFile);

    readTime = time.time() - readStartTime;

    # Draw the captioned image, again recording the time taken.

    drawStartTime = time.time();

    # Fetch the dimentions for the captioned frame.

    plotW, plotH = _CaptionedAnimationFrameDimensions;

    plt.figure(figsize = (plotW, plotH));

    # Draw the image.

    axes1 = plt.subplot(2, 1, 1);

    plt.imshow(image, interpolation = 'bilinear');

    # Add the caption.

    axes2 = plt.subplot(2, 1, 2);

    axes2.add_artist(
        AnchoredText(caption, loc = 10, frameon = False)
        );

    # Axis adjustments.

    for axes in axes1, axes2:
        axes.set_facecolor(frameColour);

        axes.set_xticks([]);
        axes.set_yticks([]);

        for spine in axes.spines.values():
            spine.set_linewidth(0.0);

    # "Magic" layout function.

    plt.tight_layout();

    # Adjust the image area based on _CaptionedAnimationFrameCaptionHeight.

    imageHeight = 1.0 - _CaptionedAnimationFrameCaptionHeight / plotH;

    axes1.set_position(
        (0.0, 1.0 - imageHeight, 1.0, imageHeight)
        );

    axes2.set_position(
        (0.0, 0.0, 1.0, 1.0 - imageHeight)
        );

    # Save and clean up.

    plt.savefig(outputPath, format = 'png', dpi = 200, facecolor = frameColour);
    plt.close();

    drawTime = time.time() - drawStartTime;

    functionTime = time.time() - startTime;

    # If the DebugMode flag is set, print out timing information from the reading/drawing parts of the function.

    if DebugMode:
        print("DEBUG: _RenderCaptionedAnimationFrame(): Read = {0:.2f} s ({1:.2f} %), Draw = {2:.2f} s ({3:.2f} %)".format(readTime, 100.0 * readTime / functionTime, drawTime, 100.0 * drawTime / functionTime));


# ----
# Main
# ----

if __name__ == "__main__":
    # ---------
    # Section 1
    # ---------

    # Read the comment lines in the merged XYZ file to extract the mode frequencies and the normal-mode coordinates associated with each animation frame.

    print("Reading \"{0}\"...".format(MergedXYZFile));

    animationData = _ReadMergedXYZFileCommentLines(MergedXYZFile);

    # Calculate the expected number of animation frames.

    expectedNumFrames = sum(
        len(modeAmplitudes) for _, _, modeAmplitudes in animationData.values()
        );

    print("  -> INFO: Expect {0} animation frames".format(expectedNumFrames));

    print("");

    # ---------
    # Section 2
    # ---------

    # Scan the bitmap folder for images.

    print("Scanning \"{0}\" for images...".format(AnimationFrameImageFolder));

    imageFiles = [];

    for entry in os.listdir(AnimationFrameImageFolder):
        absPath = os.path.join(AnimationFrameImageFolder, entry);

        if os.path.isfile(absPath):
            root, ext = os.path.splitext(entry);

            if ext == AnimationFrameExtension:
                components = root.split('.');

                if len(components) >= 2 and '.'.join(components[:-1]) == AnimationFramePrefix:
                    # To ensure the files will sort into the right numerical order, we convert the file number to an integer and store it with the file name in a tuple.

                    imageFiles.append(
                        (int(components[-1]), entry)
                        );

    # Sort by file number and strip the numbers from the file list.

    imageFiles = [os.path.join(AnimationFrameImageFolder, fileName) for _, fileName in sorted(imageFiles)];

    # Calculate the actual number of animation frames.

    numFrames = len(imageFiles);

    print("  -> INFO: Found {0} animation frames".format(numFrames));

    print("");

    # Sanity check.

    if numFrames != expectedNumFrames:
        raise Exception("Error: The number of animation frames in \"{0}\" ({1}) does not match the expected number ({2}).".format(AnimationFrameImageFolder, numFrames, expectedNumFrames));

    # Add frame image file names into animationData.

    imageFilesPointer = 0;

    for modeIndex in sorted(animationData.keys()):
        modeFrequencyTHz, modeFrequencyInvCm, modeAmplitudes = animationData[modeIndex];

        animationData[modeIndex] = (
            modeFrequencyTHz, modeFrequencyInvCm, modeAmplitudes,
            imageFiles[imageFilesPointer:imageFilesPointer + len(modeAmplitudes)]
            );

        imageFilesPointer = imageFilesPointer + len(modeAmplitudes);

    # ---------
    # Section 3
    # ---------

    # Generate animations.

    # Initialise Matplotlib.

    fontSize = 8;

    mpl.rc('font', **{ 'family' : 'serif', 'size' : fontSize, 'serif' : 'Courier New' });
    mpl.rc('mathtext', **{ 'fontset' : 'custom', 'rm' : 'Courier New', 'it' : 'Courier New:it', 'bf' : 'Courier New:bold' });

    print("Generating animations...");

    # If FrameColour is not set, read the first image, and set it to the most common (modal) pixel colour.

    if AnimationFrameBackgroundColour == None:
        image = _ReadAnimationFrame(imageFiles[0]);

        # To get the modal pixel colour using the scipy.stats mode() function, we first need to reshape the array to (width * height) x depth.

        width, height, depth = image.shape;

        modeResult = mode(
            image.reshape((width * height, 3))
            );

        # With this input data, mode() returns a 1 x depth NumPy array, which needs to be converted to a 1D array before being used as a Matplotlib colour.

        AnimationFrameBackgroundColour = modeResult.mode[0, :];

        print("  -> INFO: AnimationFrameBackgroundColour set to ({0:.2f}, {1:.2f}, {2:.2f})".format(*AnimationFrameBackgroundColour));
        print("");

    # Loop over modes.

    for modeIndex in sorted(animationData.keys()):
        outputFileName = "{0}-Mode{1:0>3}.gif".format(OutputPrefix, modeIndex);

        # If OverwriteExisting is not set, check whether the GIF file already exists.
        # If it does, print a message and skip.

        if not OverwriteExisting and os.path.isfile(outputFileName):
            print("  -> INFO: \"{0}\" already exists -> skipping...".format(outputFileName));
        else:
            print("  -> Generating animaton for Mode {0}".format(modeIndex));

            # Prepare captioned animation frames.

            fileNames = _PrepareCaptionedAnimationFrames(modeIndex, animationData[modeIndex], AnimationFrameBackgroundColour, "GIFBuild-Temp");

            # Merge into an animated GIF using Imagemagick.

            os.system(
                "convert -delay 10 -loop 0 " + " ".join(fileNames) + " {0}".format(outputFileName)
                );

            # Remove the temporary files.

            for fileName in fileNames:
                os.remove(fileName);

    print("");

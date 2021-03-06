# MolecularCrystalPhononAnimation.py by J. M. Skelton


# ----------
# Parameters
# ----------

# Path to the input file; this should be a Phonopy mesh.yaml file containing frequencies and eigenvectors at the Gamma point (q = (0, 0, 0)).

InputFile = r"mesh-eigenvectors.yaml";

# Specify bond distances (A) for expansion of the structure outside the unit-cell boundary.
# Either atom in the pair can be specified using the wildcard 'X'; the script will search for specific pairs first (e.g. 'C-H' or 'H-C'), then pairs with one wildcard ('C-X', 'X-C', 'H-X', 'X-H'), then, finally, a pair with both wildcards ('X-X').

BondDistances = {
    # Distances used by VESTA (for organic crystals).

    #'C-O' : 1.97249,
    #'C-C' : 1.89002,
    #'C-H' : 1.2,
    #'O-H' : 1.2

    # Distances for MAPbI3.

    'C-H' : 1.60,
    'C-N' : 1.80,
    'N-H' : 1.60,
    'Pb-I' : 3.50
    };

# Integer supercell in which to expand the structure along the three crystallographic axes (a, b, c).
# An expansion of (N_a, N_b, N_c) that the supercell will be generated by padding the unit cell along the +/- a, b and c directions with N_a, N_b and N_c additional unit cells, respectively.

StructureExpansionSC = (1, 1, 1);

# Restrict atoms included in the expansion when expanding the structure outside the unit-cell boundary.
# Atoms entered into this list more than the set distance (in fractional units, along one or more lattice vectors) from the central unit cell will not be included in the expansion.
# This can be used for e.g. metal nodes in coordination polymers (MOFs) or the atoms at the centre octahedra in perovskites.

RestrictExpansionAtoms = {
    # For limiting expansion of the octahedral framework in MAPbI3.

    'Pb' : 0.2
    };

# Scale the eigendisplacements so that the maximum Cartesian displacement is 1 A.
# With this setting, the normal-mode amplitude is automatically adjusted so as to effectively specify (maximum) Cartesian displacement distances.

ScaleDisplacements = True;

MaxAmplitude = 0.25;

# Number of modulation steps.

ModulationSteps = 32;

# Generate animations for a subset of modes.
# Specified as a tuple of (selection, vMin, vMax) values.
# Select can be one of 'index' (from 1..3N), 'freq_thz' or 'freq_invcm'.
# Set to None to generate animations for all modes.

ModeSelect = None; # ('index', 4, 5);

# Prefix for the output files.

OutputPrefix = "MolecularCrystal";


# -------
# Imports
# -------

import math;
import os;
import pickle;
import tarfile;
import time;

import yaml;

import numpy as np;


# ---------
# Constants
# ---------

_PickleDumpFile = r"MolecularCrystalPhononAnimation.bin";

# Value taken from: http://halas.rice.edu/conversions (accessed 3/4/2017).

_THzToInverseCm = 33.35641;

# Workaround for an intermittent permissions error on Windows - see below.

_DeleteFilePermissionErrorDelay = 0.5;


# ---------
# Functions
# ---------

def _ReadYAMLFile(filePath):
    latticeVectors = None;
    atomTypes, atomPositions, sqrtAtomicMasses = None, None, None;
    frequencies, eigenvectors = None, None;

    # Parse the input file.

    with open(filePath) as inputReader:
        inputYAML = yaml.load(inputReader);

        # Read the lattice vectors.

        latticeVectors = [
            np.array(vector, dtype = np.float64) for vector in inputYAML['lattice']
            ];

        # Read the atomic symbols (atom types) positions and masses.

        atomTypes = [atom['symbol'] for atom in inputYAML['atoms']];
        atomPositions = [np.array(atom['position'], dtype = np.float64) for atom in inputYAML['atoms']];

        sqrtAtomicMasses = [math.sqrt(atom['mass']) for atom in inputYAML['atoms']];

        # Scan the file for Gamma-point frequencies and eigenvectors.

        for qPoint in inputYAML['phonon']:
            qx, qy, qz = qPoint['q-position'];

            if qx == qy == qz == 0.0:
                frequencies, eigenvectors = [], [];

                for band in qPoint['band']:
                    frequencies.append(band['frequency']);

                    eigenvector = [];

                    for i, component in enumerate(band['eigenvector']):
                        # The Gamma-point eigenvectors are real, so we only need to store the real part of the complex numbers.

                        eigenvector.append(
                            np.array([item[0] for item in component], dtype = np.float64)
                            );

                    eigenvectors.append(eigenvector);

                break;

    # Check a set of frequencies and eigenvectors were successfully extracted.

    if frequencies == None:
        raise Exception("Error: Gamma-point frequencies and eigenvectors were not found in the input YAML file.");

    # Divide the eigenvector components by sqrt(mass) to generate the eigendisplacements.

    eigendisplacements = [];

    for eigenvector in eigenvectors:
        eigensdisplacement = [
            component / sqrtAtomicMasses[i] for i, component in enumerate(eigenvector)
            ];

        eigendisplacements.append(eigensdisplacement);

    # Return the data.

    return (
        (latticeVectors, atomTypes, atomPositions),
        (frequencies, eigenvectors, eigendisplacements)
        );

def _WriteXYZFile(atomTypes, atomPositionSets, filePath, commentLines = None):
    # Sanity checks.

    if commentLines != None and len(commentLines) != len(atomPositionSets):
        raise Exception("Error: If supplied, commentLines must contain the same number of entries as atomPositionSets.");

    for i, atomPositionSet in enumerate(atomPositionSets):
        if len(atomPositionSet) != len(atomTypes):
            raise Exception("Error: Atom position set {0} is does not contain the same number of elements as atomTypes.".format(i + 1));

    # Write out the data in the XYZ format.

    atomCountLine = "{0}\n".format(len(atomTypes));

    with open(filePath, 'w') as outputWriter:
        for atomPositionSet, commentLine in zip(atomPositionSets, commentLines):
            outputWriter.write(atomCountLine);

            outputWriter.write("{0}\n".format(commentLine));

            for atomType, (x, y, z) in zip(atomTypes, atomPositionSet):
                outputWriter.write("  {0: >3}  {1: 16.10f}  {2: 16.10f}  {3: 16.10f}\n".format(atomType, x, y, z));


# ----
# Main
# ----

if __name__ == "__main__":
    # ---------
    # Section 1
    # ---------

    # Load input data.

    print("Loading input data...");

    structure, phononModes = None, None;

    # Since parsing YAML files is very slow, we pickle the data for faster loading next time the script is run.
    # The dump stores the path to the input file, which we use to (in)validate the dump.

    # If _PickleDumpFile is present, read it and see whether the stored file path matches InputFile.

    if os.path.isfile(_PickleDumpFile):
        pFilePath, pStructure, pPhononModes = None, None, None;

        try:
            with open(_PickleDumpFile, 'rb') as inputReader:
                pFilePath, pStructure, pPhononModes = pickle.load(inputReader);

            if pFilePath == InputFile:
                # If the file path matches, use the unpickled data.

                structure, phononModes = pStructure, pPhononModes;

                print("  -> INFO: Loaded pickled data from {0}".format(_PickleDumpFile));
            else:
                # If not, remove the "stale" dump file.

                os.remove(_PickleDumpFile);

                print("  -> INFO: Removed \"stale\" pickle dump file {0}".format(_PickleDumpFile));
        except UnicodeDecodeError:
            # Reading pickle dump files can fail with a UnicodeDecodeError due to incompatibilities between major versions of Python.
            # If this happens, delete the file and try re-reading the source.

            os.remove(_PickleDumpFile);

            print("  -> INFO: An error occurred while reading pickle dump file {0} -> it has been deleted".format(_PickleDumpFile));

    # If required, read and parse the input file.

    if structure == None:
        print("  -> Reading: {0}".format(InputFile));

        structure, phononModes = _ReadYAMLFile(InputFile);

        # Store the data to a pickle dump file.

        with open(_PickleDumpFile, 'wb') as outputWriter:
            pickle.dump(
                (InputFile, structure, phononModes), outputWriter
                );

            print("  -> INFO: Pickled data to dump file {0}".format(_PickleDumpFile));

    latticeVectors, atomTypes, atomPositions = structure;
    frequencies, eigenvectors, eigendisplacements = phononModes;

    print("");

    # ---------
    # Section 2
    # ---------

    # Generate the structure expansion.

    print("Expanding structure...");

    # Build a supercell.

    nAtoms = len(atomPositions);

    scDim1, scDim2, scDim3 = StructureExpansionSC;

    # scAtomMappings keeps track of how the atoms in the supercell map onto the atoms in the original cell.

    scAtomPositions, scAtomMappings = [], [];

    for z in range(-scDim3, scDim3 + 1):
        for y in range(-scDim2, scDim2 + 1):
            for x in range(-scDim1, scDim1 + 1):
                scVector = np.array([x, y, z], dtype = np.float64);

                scAtomPositions.extend(
                    [position + scVector for position in atomPositions]
                    );

                scAtomMappings.extend(
                    [i for i in range(0, nAtoms)]
                    );

    # Convert the positions from fractional to cartesian coordinates.

    a, b, c = latticeVectors;

    scAtomPositionsCart = [a * fA + b * fB + c * fC for fA, fB, fC in scAtomPositions];

    # We need to generate a list of atoms to include in the expansion, and their mapping to atoms in the original cell.

    # First we add the atoms corresponding to the base unit cell (at the centre of the supercell expansion).

    baseIndex = (len(scAtomPositions) - nAtoms) // 2;

    expAtomPositions = scAtomPositionsCart[baseIndex:baseIndex + nAtoms];
    expAtomMappings = scAtomMappings[baseIndex:baseIndex + nAtoms];

    # The positions of atoms from the supercell that are included in the expansion are set to None.

    for i in range(baseIndex, baseIndex + nAtoms):
        scAtomPositionsCart[i] = None;

    # Next, we cycle through the remaining atoms in the supercell, check the bond distance to atoms included in the expansion and, if the distance is less than the cutoff, include them.
    # This is repeated until no additional atoms are added in the final cycle.

    # "Canonicalise" bond distances to reduce the amount of work required to lookup distances.

    bondDistances = { };

    for key, value in BondDistances.items():
        type1, type2 = key.split('-');

        newKey = '-'.join(sorted([type1, type2]));

        if newKey in bondDistances:
            raise Exception("Error: '{0}' distance set twice in BondDistances - '{0}' and '{1}' are equivalent.".format(key, newKey));

        bondDistances[newKey] = value;

    # For printing status messages.

    cycleNumber = 1;

    # To limit the number of warning messages printed.

    pairKeysMissing = [];

    while True:
        addedAtoms = 0;

        for i, (position1, position1Cart, mapIndex1) in enumerate(zip(scAtomPositions, scAtomPositionsCart, scAtomMappings)):
            if position1Cart is not None:
                type1 = atomTypes[mapIndex1];

                # If the supercell position hasn't been set to None, first check whether the atom type appears in the exclude list.

                if type1 in RestrictExpansionAtoms:
                    # If so, check the fractional coordinates and decide whether to skip checking whether or not to include it.

                    skipAtom = False;

                    # If any of the fractional coordinates are outside the range [0, 1], check whether the absolute value is greater than the value set in RestrictExpansionAtoms.

                    for f in position1:
                        if f < 0.0 or f >= 1.0:
                            # If the fractional coordinate is >= 1, adjust it for comparison.

                            if f >= 1.0:
                                f = f - 1.0;

                            if math.fabs(f) > RestrictExpansionAtoms[type1]:
                                skipAtom = True;
                                break;

                    if skipAtom:
                        continue;

                # Calculate the bond distance to atoms in the include list and compare them to the reference bond distances.

                for position2Cart, mapIndex2 in zip(expAtomPositions, expAtomMappings):
                    type2 = atomTypes[mapIndex2];

                    # Look up a reference bond distance to compare to.

                    pairKey = '-'.join(sorted([type1, type2]));

                    # First check this pair hasn't already been checked and found missing - if it is, there's no point doing the work to search for it.

                    if pairKey not in pairKeysMissing:
                        testDistance = None;

                        testKeys = [pairKey] + ['-'.join(sorted(pair)) for pair in [(type1, 'X'), ('X', type2), ('X', 'X')]];

                        for testKey in testKeys:
                            if testKey in bondDistances:
                                testDistance = bondDistances[testKey];

                        # If no reference distance is found, print a warning and add the pair key to the list of missing pair keys.

                        if testDistance == None:
                            pairKeysMissing.append(pairKey);

                            print("  -> WARNING: No reference bond distance for atom pair '{0}', '{1}' (including with wildcards) found in BondDistances.".format(type1, type2));
                        else:
                            if np.linalg.norm(position1Cart - position2Cart) <= testDistance:
                                # If the distance is less than or equal to the reference, add the atom to the include list, and set the position in the supercell list to None.

                                expAtomPositions.append(position1Cart);
                                expAtomMappings.append(mapIndex1);

                                scAtomPositionsCart[i] = None;

                                addedAtoms = addedAtoms + 1;

                                break;

        print("  -> INFO: Expansion cycle {0} added {1} atom(s)".format(cycleNumber, addedAtoms));

        cycleNumber = cycleNumber + 1;

        # If not atoms were added during this cycle, break.

        if addedAtoms == 0:
            break;

    print("");

    # Build a list of atom types to accompany the expanded structure.

    expAtomTypes = [atomTypes[i] for i in expAtomMappings];

    # Write out the expanded structure in XYZ format.

    fileName = r"{0}_StructureExpansion.xyz".format(OutputPrefix);

    print("Writing expanded structure to \"{0}\"".format(fileName));

    _WriteXYZFile(
        expAtomTypes, [expAtomPositions], fileName,
        commentLines = ["Expanded Structure"]
        );

    print("");

    # ---------
    # Section 3
    # ---------

    # Select the range of modes to output.

    index1, index2 = None, None;

    if ModeSelect != None:
        # If ModeSelect is set, work out which indices to slice between.

        selection, vMin, vMax = ModeSelect;

        # Sanity check.

        if vMin != None and vMax != None and vMin >= vMax:
            raise Exception("Error: If using ModeSelect, vMin must be < vMax.");

        if selection == 'index':
            # If the 'index' option is set, perform bounds checks on whichever of vMin and vMax are set.

            if vMin != None and (vMin < 1 or vMin > len(frequencies)):
                raise Exception("Error: If using ModeSelect with the 'index' option, vMin (if set) must be between 1 and 3N.");

            if vMax != None and (vMax < 1 or vMax > len(frequencies)):
                raise Exception("Error: If using ModeSelect with the 'index' option, vMax (if set) must be between 2 and 3N.");

            # Convert the user-input one-based indices to Python zero-based indices.

            index1 = vMin - 1 if vMin != None else 0;
            index2 = vMax if vMax != None else len(frequencies) - 1;

        elif selection == 'freq_thz' or selection == 'freq_invcm':
            # If one of the 'freq_*' options is set, scan a list of frequencies to set the selection.

            selectFrequencies = None;

            if selection == 'freq_thz':
                selectFrequencies = frequencies;
            elif selection == 'freq_invcm':
                selectFrequencies = [frequency * _THzToInverseCm for frequency in frequencies];

            if vMin != None:
                # If vMin is set, set the first index based on this value.

                for i, frequency in enumerate(selectFrequencies):
                    if frequency >= vMin:
                        index1 = i;
                        break;

                # If vMin is found to be higher than the highest phonon frequency, index1 will not be set.
                # If this happens, throw an error.

                if index1 == None:
                    raise Exception("Error: If ModeSelect is used with one of the 'freq_*' options, vMin (if set) must be within the range spanned by the phonon frequencies.");
            else:
                # If vMin is not set, start from the first mode.

                index1 = 0;

            if vMax != None:
                # If vMax is set, try to set the second index.
                # If the maximum is higher than the highest phonon frequency, the index should end up equal to 3N.

                index2 = index1 + 1;

                while index2 < len(selectFrequencies):
                    if selectFrequencies[index2] >= vMax:
                        break;

                    index2 = index2 + 1;
            else:
                # If not, set the second index to 3N.

                index2 = len(selectFrequencies);
    else:
        # If ModeSelect is not set, animate all the modes.

        index1, index2 = 0, len(frequencies);

    # Generate modulated structures.

    print("Generating modulated positions...");

    # If ScaleDisplacements is set, the eigendisplacements are scaled so that a normal-mode amplitude of 1 corresponds to a maximum cartesian displacement of 1 A.

    scaleFactors = None;

    if ScaleDisplacements:
        scaleFactors = [None for i in range(0, len(frequencies))];

        for i in range(index1, index2):
            scaleFactors[i] = max(np.linalg.norm(vector) for vector in eigendisplacements[i]);

    # The modulation is a cosine oscilaltion between +/- MaxDisplacement.
    # We add a phase factor of 90 degrees (pi/2) so that the oscillation starts at q = 0.
    # The step size is chosen assuming that the animation will be played in a loop i.e. it avoids the amplitudes of steps 1 and N both being zero.

    modulationStep = (2.0 * math.pi) / ModulationSteps;

    modulationAmplitudes = np.cos(
        np.array([i * modulationStep for i in range(0, ModulationSteps)], dtype = np.float64) + math.pi / 2.0
        );

    modulationAmplitudes = modulationAmplitudes * MaxAmplitude;

    modulationPositionSets, modulationAmplitudeSets = [], [];

    # Loop over modes.

    for modeIndex in range(index1, index2):
        modeFrequency = frequencies[modeIndex];

        print("  -> mode = {0: >4}, v = {1: >8.3f} THz ({2: >8.2f} cm^-1)".format(modeIndex + 1, modeFrequency, modeFrequency * _THzToInverseCm));

        eigendisplacement = eigendisplacements[modeIndex];

        modulationPositionSet, modulationAmplitudeSet = [], [];

        # Loop over amplitudes.

        for amplitude in modulationAmplitudes:
            # Scale the amplitude if required.

            if scaleFactors != None:
                amplitude = amplitude / scaleFactors[modeIndex];

            modulationPositionSet.append(
                [position + amplitude * eigendisplacement[index] for position, index in zip(expAtomPositions, expAtomMappings)]
                );

            modulationAmplitudeSet.append(amplitude);

        modulationPositionSets.append(modulationPositionSet);
        modulationAmplitudeSets.append(modulationAmplitudeSet);

    print("");

    # ---------
    # Section 4
    # ---------

    # Write modulation animations to separate XYZ-format files.
    # Since there may be a lot if these, we store them in a .tar.gz file.

    fileName = "{0}_Animations.tar.gz".format(OutputPrefix);

    print("Writing XYZ-format animations to \"{0}\"...".format(fileName));

    with tarfile.open(fileName, 'w:gz') as archiveFile:
        for i, (modulationPositionSet, modulationAmplitudeSet) in enumerate(zip(modulationPositionSets, modulationAmplitudeSets)):
            modeIndex = index1 + i;

            xyzFileName = "Mode-{0:0>3}.xyz".format(modeIndex + 1);

            print("  -> {0}".format(xyzFileName));

            modeFrequency = frequencies[modeIndex];

            _WriteXYZFile(
                expAtomTypes, modulationPositionSet, xyzFileName,
                commentLines = ["v = {0: >8.3f} THz ({1: >8.2f} cm^-1), q = {2: >8.3f} amu^1/2 A".format(modeFrequency, modeFrequency * _THzToInverseCm, amplitude) for amplitude in modulationAmplitudeSet]
                );

            archiveFile.add(
                xyzFileName, arcname = r"Animations/{0}".format(xyzFileName)
                );

            # There's an issue/odd behaviour (?) on Windows whereby deleting the file immediately after archiving sometimes throws a PermissionError.
            # This may be due to the script being run in Dropbox and the Dropbox syncing not being able to keep up.
            # If this happens, catch the first error, sleep for a preset short time delay, then try again.

            try:
                os.remove(xyzFileName);
            except PermissionError:
                time.sleep(_DeleteFilePermissionErrorDelay);
                os.remove(xyzFileName);

    print("");

    # Merge all the modulation animations into a single XYZ-format file.
    # This is to make it easier to create animations later.

    fileName = "{0}_Animations-Merged.xyz".format(OutputPrefix);

    print("Writing merged XYZ-format animations to \"{0}\"...".format(fileName));

    # First, we build lists of merged modulated structures and comment lines.
    # The comment lines record the mode index, frequency and normal-mode coordinate for further processing.

    structures, commentLines = [], [];

    for i, (modulationPositionSet, modulationAmplitudeSet) in enumerate(zip(modulationPositionSets, modulationAmplitudeSets)):
        structures.extend(modulationPositionSet);

        modeIndex = index1 + i;
        modeFrequency = frequencies[modeIndex];

        commentLines.extend(
            ["mode = {0: >4}, v = {1: >8.3f} THz ({2: >8.2f} cm^-1), q = {3: >8.3f} amu^1/2 A".format(modeIndex + 1, modeFrequency, modeFrequency * _THzToInverseCm, amplitude) for amplitude in modulationAmplitudeSet]
            );

    # Write out the data.

    _WriteXYZFile(expAtomTypes, structures, fileName, commentLines);

    print("");

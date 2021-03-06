# Copyright (C) 2020 Atsushi Togo
# All rights reserved.
#
# This file is part of phonopy.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in
#   the documentation and/or other materials provided with the
#   distribution.
#
# * Neither the name of the phonopy project nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import sys
import os
import numpy as np
from phonopy import Phonopy, __version__
from phonopy.structure.cells import print_cell
from phonopy.structure.atoms import atom_data, symbol_map
from phonopy.interface.phonopy_yaml import PhonopyYaml
from phonopy.interface.fc_calculator import fc_calculator_names
from phonopy.interface.calculator import (
    get_interface_mode, write_supercells_with_displacements,
    get_default_physical_units, get_default_displacement_distance)
from phonopy.interface.vasp import create_FORCE_CONSTANTS
from phonopy.phonon.band_structure import (
    get_band_qpoints, get_band_qpoints_by_seekpath)
from phonopy.phonon.dos import get_pdos_indices
from phonopy.file_IO import (
    parse_FORCE_CONSTANTS, parse_FORCE_SETS,
    write_FORCE_CONSTANTS, write_force_constants_to_hdf5,
    get_born_parameters, parse_QPOINTS, is_file_phonopy_yaml)
from phonopy.cui.create_force_sets import create_FORCE_SETS
from phonopy.cui.load_helper import (
    read_force_constants_from_hdf5, get_nac_params,
    set_dataset_and_force_constants)
from phonopy.cui.show_symmetry import check_symmetry
from phonopy.cui.settings import PhonopyConfParser
from phonopy.cui.collect_cell_info import collect_cell_info
from phonopy.cui.phonopy_argparse import (
    get_parser, show_deprecated_option_warnings)


# AA is created at http://www.network-science.de/ascii/.
def print_phonopy():
    print("""        _
  _ __ | |__   ___  _ __   ___   _ __  _   _
 | '_ \| '_ \ / _ \| '_ \ / _ \ | '_ \| | | |
 | |_) | | | | (_) | | | | (_) || |_) | |_| |
 | .__/|_| |_|\___/|_| |_|\___(_) .__/ \__, |
 |_|                            |_|    |___/""")


def print_version(version, package_name="phonopy"):
    try:
        version_text = ('%s' % version).rjust(44)
        import pkg_resources
        dist = pkg_resources.get_distribution(package_name)
        if dist.has_version():
            ver = dist.version.split('.')
            if len(ver) > 3:
                rev = ver[3]
                version_text = ('%s-r%s' % (version, rev)).rjust(44)
    except ImportError:
        pass
    except Exception as err:
        if (err.__module__ == 'pkg_resources' and
            err.__class__.__name__ == 'DistributionNotFound'):
            pass
        else:
            raise
    finally:
        print(version_text)
        print('')


def print_end():
    print("""                 _
   ___ _ __   __| |
  / _ \ '_ \ / _` |
 |  __/ | | | (_| |
  \___|_| |_|\__,_|
""")


def print_error():
    print("""  ___ _ __ _ __ ___  _ __
 / _ \ '__| '__/ _ \| '__|
|  __/ |  | | | (_) | |
 \___|_|  |_|  \___/|_|
""")


def print_attention(attention_text):
    print("*" * 67)
    print(attention_text)
    print("*" * 67)
    print('')


def print_error_message(message):
    print('')
    print(message)


def file_exists(filename, log_level, is_any=False):
    if os.path.exists(filename):
        return True
    else:
        if is_any:
            return False
        else:
            error_text = "\"%s\" was not found." % filename
            print_error_message(error_text)
            if log_level > 0:
                print_error()
            sys.exit(1)


def files_exist(filename_list, log_level, is_any=False):
    filenames = []
    for filename in filename_list:
        if file_exists(filename, log_level, is_any=is_any):
            filenames.append(filename)

    if filenames:
        return filenames
    else:
        if len(filenames) == 2:
            all_filenames = "\"%s\" or \"%s\"" % tuple(filenames)
        else:
            all_filenames = ", ".join(["\"%s\"" %
                                       fn for fn in filename_list[:-1]])
            all_filenames += " or \"%s\"" % filename_list[-1]
        error_text = "Any of %s was not found." % all_filenames
        print_error_message(error_text)
        if log_level > 0:
            print_error()
        sys.exit(1)


def finalize_phonopy(log_level,
                     settings,
                     confs,
                     phonon,
                     filename="phonopy.yaml"):
    units = get_default_physical_units(phonon.calculator)

    yaml_settings = {
        'force_sets': settings.get_include_force_sets(),
        'force_constants': settings.get_include_force_constants(),
        'born_effective_charge': settings.get_include_born_effective_charge(),
        'dielectric_constant': settings.get_include_dielectric_constant(),
        'displacements': settings.get_include_displacements(),
    }

    phpy_yaml = PhonopyYaml(configuration=confs,
                            physical_units=units,
                            settings=yaml_settings)
    phpy_yaml.set_phonon_info(phonon)
    with open(filename, 'w') as w:
        w.write(str(phpy_yaml))

    if log_level > 0:
        print("")
        print("Summary of calculation was written in \"%s\"." % filename)
        print_end()
    sys.exit(0)


def print_cells(phonon, unitcell_filename):
    supercell = phonon.get_supercell()
    unitcell = phonon.get_unitcell()
    primitive = phonon.get_primitive()
    p2p_map = primitive.get_primitive_to_primitive_map()
    mapping = np.array(
        [p2p_map[x] for x in primitive.get_supercell_to_primitive_map()],
        dtype='intc')
    s_indep_atoms = phonon.get_symmetry().get_independent_atoms()
    p_indep_atoms = mapping[s_indep_atoms]
    u2s_map = supercell.get_unitcell_to_supercell_map()
    print("-" * 30 + " primitive cell " + "-" * 30)
    print_cell(primitive, stars=p_indep_atoms)
    print("-" * 32 + " unit cell " + "-" * 33)  # 32 + 11 + 33 = 76
    u2u_map = supercell.get_unitcell_to_unitcell_map()
    u_indep_atoms = [u2u_map[x] for x in s_indep_atoms]
    print_cell(unitcell, mapping=mapping[u2s_map], stars=u_indep_atoms)
    print("-" * 32 + " super cell " + "-" * 32)
    print_cell(supercell, mapping=mapping, stars=s_indep_atoms)
    print("-" * 76)


def print_settings(settings,
                   phonon,
                   is_primitive_axes_auto,
                   unitcell_filename,
                   load_phonopy_yaml):
    primitive_matrix = phonon.primitive_matrix
    supercell_matrix = phonon.supercell_matrix
    interface_mode = phonon.calculator
    run_mode = settings.get_run_mode()
    if interface_mode:
        print("Calculator interface: %s" % interface_mode)
    if (settings.get_cell_filename() is not None and
        settings.get_cell_filename() != unitcell_filename):
        print("\"%s\" was not able to be used."
              % settings.get_cell_filename())
    print("Crystal structure was read from \"%s\"." % unitcell_filename)
    physical_units = get_default_physical_units(interface_mode)
    print("Unit of length: %s" % physical_units['length_unit'])
    if is_band_auto(settings) and not is_primitive_axes_auto:
        print("Automatic band structure mode forced automatic choice "
              "of primitive axes.")
    if run_mode == 'band':
        if is_band_auto(settings):
            print("Band structure mode (Auto)")
        else:
            print("Band structure mode")
    if run_mode == 'mesh':
        print("Mesh sampling mode")
    if run_mode == 'band_mesh':
        print("Band structure and mesh sampling mode")
    if run_mode == 'anime':
        print("Animation mode")
    if run_mode == 'modulation':
        print("Modulation mode")
    if run_mode == 'irreps':
        print("Ir-representation mode")
    if run_mode == 'qpoints':
        if settings.get_write_dynamical_matrices():
            print("QPOINTS mode (dynamical matrices written out)")
        else:
            print("QPOINTS mode")
    if ((run_mode == 'band' or run_mode == 'mesh' or run_mode == 'qpoints') and
        settings.get_is_group_velocity()):
        gv_delta_q = settings.get_group_velocity_delta_q()
        if gv_delta_q is not None:
            print("  With group velocity calculation (dq=%3.1e)" % gv_delta_q)
        else:
            print('')
    if settings.get_create_displacements():
        print("Displacements creation mode")
        if not settings.get_is_plusminus_displacement() == 'auto':
            if settings.get_is_plusminus_displacement():
                print("  Plus Minus displacement: full plus minus directions")
            else:
                print("  Plus Minus displacement: only one direction")
        if not settings.get_is_diagonal_displacement():
            print("  Diagonal displacement: off")
        if settings.get_random_displacements():
            print("  Number of supercells with random displacements: %d"
                  % settings.get_random_displacements())
            if settings.get_random_seed() is not None:
                print("  Random seed: %d" % settings.get_random_seed())

    print("Settings:")
    if load_phonopy_yaml:
        if not settings.get_is_nac():
            print("  Non-analytical term correction (NAC): off")
    else:
        if settings.get_is_nac():
            print("  Non-analytical term correction (NAC): on")
            if settings.get_nac_q_direction() is not None:
                print("  NAC q-direction: %s" % settings.get_nac_q_direction())
    if settings.get_fc_spg_symmetry():
        print("  Enforce space group symmetry to force constants: on")
    if load_phonopy_yaml:
        if not settings.get_fc_symmetry():
            print("  Force constants symmetrization: off")
    else:
        if settings.get_fc_symmetry():
            print("  Force constants symmetrization: on")
    if settings.get_lapack_solver():
        print("  Use Lapack solver via Lapacke: on")
    if settings.get_symmetry_tolerance() is not None:
        print("  Symmetry tolerance: %5.2e"
              % settings.get_symmetry_tolerance())
    if run_mode == 'mesh' or run_mode == 'band_mesh':
        mesh = settings.get_mesh_numbers()
        if type(mesh) is float:
            print("  Length for sampling mesh: %.1f" % mesh)
        elif mesh is not None:
            print("  Sampling mesh: %s" % np.array(mesh))
        if settings.get_is_thermal_properties():
            cutoff_freq = settings.get_cutoff_frequency()
            if cutoff_freq is None:
                pass
            elif cutoff_freq < 0:
                print("  - Thermal properties are calculatd with "
                      "absolute phonon frequnecy.")
            else:
                print("  - Phonon frequencies > %5.3f are used to calculate "
                      "thermal properties." % cutoff_freq)
        elif (settings.get_is_thermal_displacements() or
              settings.get_is_thermal_displacement_matrices()):
            fmin = settings.get_min_frequency()
            fmax = settings.get_max_frequency()
            text = None
            if (fmin is not None) and (fmax is not None):
                text = "  - Phonon frequency from %5.3f to %5.3f" % (fmin,
                                                                     fmax)
                text += " are used to calculate\n"
                text += "    thermal displacements."
            elif (fmin is None) and (fmax is not None):
                text = "Phonon frequency < %5.3f" % fmax
                text = ("  - %s are used to calculate thermal displacements." %
                        text)
            elif (fmin is not None) and (fmax is None):
                text = "Phonon frequency > %5.3f" % fmin
                text = ("  - %s are used to calculate thermal displacements." %
                        text)
            if text:
                print(text)
    if (np.diag(np.diag(supercell_matrix)) - supercell_matrix).any():
        print("  Supercell matrix:")
        for v in supercell_matrix:
            print("    %s" % v)
    else:
        print("  Supercell: %s" % np.diag(supercell_matrix))
    if is_primitive_axes_auto or is_band_auto(settings):
        print("  Primitive matrix (Auto):")
        for v in primitive_matrix:
            print("    %s" % v)
    elif primitive_matrix is not None:
        print("  Primitive matrix:")
        for v in primitive_matrix:
            print("    %s" % v)


def write_displacements_files_then_exit(phonon,
                                        settings,
                                        confs,
                                        optional_structure_info,
                                        log_level):
    """Write supercells with displacements and displacement dataset

    Note
    ----
    From phonopy v1.15.0, displacement dataset is written into
    phonopy_disp.yaml.

    """

    cells_with_disps = phonon.supercells_with_displacements
    additional_info = {'supercell_matrix': phonon.supercell_matrix}
    write_supercells_with_displacements(phonon.calculator,
                                        phonon.supercell,
                                        cells_with_disps,
                                        optional_structure_info,
                                        additional_info=additional_info)

    if log_level > 0:
        print("\"phonopy_disp.yaml\" and supercells have been created.")

    settings.set_include_displacements(True)

    finalize_phonopy(log_level,
                     settings,
                     confs,
                     phonon,
                     filename="phonopy_disp.yaml")


def create_FORCE_SETS_from_args(args, log_level):
    interface_mode = get_interface_mode(vars(args))
    if args.force_sets:
        filenames = args.force_sets
        force_sets_zero_mode = False
    elif args.force_sets_zero:
        filenames = args.force_sets_zero
        force_sets_zero_mode = True
    else:
        print_error_message("Something wrong for parsing arguments.")
        sys.exit(0)

    disp_filenames = files_exist(['phonopy_disp.yaml', 'disp.yaml'],
                                 log_level, is_any=True)
    if disp_filenames[0] == 'phonopy_disp.yaml':
        try:
            phpy_yaml = PhonopyYaml()
            phpy_yaml.read('phonopy_disp.yaml')
            if phpy_yaml.calculator is not None:
                interface_mode = phpy_yaml.calculator
            disp_filename = 'phonopy_disp.yaml'
        except KeyError:
            file_exists('disp.yaml', log_level)
            if log_level > 0:
                print("\"phonopy_disp.yaml\" was found but wasn't used "
                      "because of the old-style format.")
            disp_filename = 'disp.yaml'
    else:
        disp_filename = disp_filenames[0]

    files_exist(filenames, log_level)

    error_num = create_FORCE_SETS(
        interface_mode,
        filenames,
        symmetry_tolerance=args.symmetry_tolerance,
        wien2k_P1_mode=args.is_wien2k_p1,  # For test only
        force_sets_zero_mode=force_sets_zero_mode,
        disp_filename=disp_filename,
        log_level=log_level)
    if log_level > 0:
        print_end()
    sys.exit(error_num)


def produce_force_constants(phonon,
                            settings,
                            phpy_yaml,
                            unitcell_filename,
                            log_level):
    num_satom = len(phonon.supercell)
    p2s_map = phonon.primitive.p2s_map

    if settings.get_read_force_constants():
        if settings.get_is_hdf5() or settings.get_readfc_format() == 'hdf5':
            try:
                import h5py
            except ImportError:
                print_error_message("You need to install python-h5py.")
                if log_level:
                    print_error()
                sys.exit(1)

            file_exists("force_constants.hdf5", log_level)
            fc = read_force_constants_from_hdf5(
                filename="force_constants.hdf5",
                p2s_map=p2s_map,
                calculator=phonon.calculator)
            fc_filename = "force_constants.hdf5"
        else:
            file_exists("FORCE_CONSTANTS", log_level)
            fc = parse_FORCE_CONSTANTS(filename="FORCE_CONSTANTS",
                                       p2s_map=p2s_map)
            fc_filename = "FORCE_CONSTANTS"

        if log_level:
            print("Force constants are read from \"%s\"." % fc_filename)

        if fc.shape[1] != num_satom:
            error_text = ("Number of atoms in supercell is not consistent "
                          "with the matrix shape of\nforce constants read "
                          "from ")
            if (settings.get_is_hdf5() or
                settings.get_readfc_format() == 'hdf5'):
                error_text += "force_constants.hdf5.\n"
            else:
                error_text += "FORCE_CONSTANTS.\n"
            error_text += ("Please carefully check DIM, FORCE_CONSTANTS, "
                           "and %s.") % unitcell_filename
            print_error_message(error_text)
            if log_level:
                print_error()
            sys.exit(1)

        phonon.force_constants = fc
    else:
        def read_force_sets_from_phonopy_yaml(phpy_yaml):
            if (phpy_yaml.dataset is not None and
                ('forces' in phpy_yaml.dataset or
                 ('first_atoms' in phpy_yaml.dataset and
                  'forces' in phpy_yaml.dataset['first_atoms'][0]))):
                return phpy_yaml.dataset
            else:
                return None

        force_sets = None

        if phpy_yaml is not None:
            force_sets = read_force_sets_from_phonopy_yaml(phpy_yaml)
            if log_level:
                if force_sets is None:
                    print("Forces and displacements were not found in \"%s\"."
                          % unitcell_filename)
                else:
                    print("Forces and displacements were read from \"%s\"."
                          % unitcell_filename)

        if force_sets is None:
            file_exists("FORCE_SETS", log_level)
            force_sets = parse_FORCE_SETS(natom=num_satom)
            if log_level:
                print("Forces and displacements were read from \"%s\"."
                      % "FORCE_SETS")

        if (log_level and
            force_sets is not None and
            'displacements' in force_sets):
            print("%d snapshots were found."
                  % len(force_sets['displacements']))

        if 'natom' in force_sets:
            natom = force_sets['natom']
        else:
            natom = force_sets['forces'].shape[1]
        if natom != num_satom:
            error_text = "Number of atoms in supercell is not consistent with "
            error_text += "the data in FORCE_SETS.\n"
            error_text += ("Please carefully check DIM, FORCE_SETS,"
                           " and %s") % unitcell_filename
            print_error_message(error_text)
            if log_level:
                print_error()
            sys.exit(1)

        (fc_calculator,
         fc_calculator_options) = get_fc_calculator_params(settings)

        phonon.dataset = force_sets
        if log_level:
            if fc_calculator is not None:
                print("Force constants calculation by %s starts."
                      % fc_calculator_names[fc_calculator])
            else:
                print("Computing force constants...")

        if settings.get_fc_spg_symmetry() or settings.get_is_full_fc():
            # Need to calculate full force constant tensors
            phonon.produce_force_constants(
                fc_calculator=fc_calculator,
                fc_calculator_options=fc_calculator_options)
        else:
            # Only force constants between atoms in primitive cell and
            # supercell
            phonon.produce_force_constants(
                calculate_full_force_constants=False,
                fc_calculator=fc_calculator,
                fc_calculator_options=fc_calculator_options)


def store_force_constants(phonon,
                          settings,
                          phpy_yaml,
                          unitcell_filename,
                          load_phonopy_yaml,
                          log_level):
    physical_units = get_default_physical_units(phonon.calculator)
    p2s_map = phonon.primitive.p2s_map

    if load_phonopy_yaml:
        (fc_calculator,
         fc_calculator_options) = get_fc_calculator_params(settings)
        is_full_fc = (settings.get_fc_spg_symmetry() or
                      settings.get_is_full_fc())
        set_dataset_and_force_constants(
            phonon,
            phpy_yaml.dataset,
            phpy_yaml.force_constants,
            fc_calculator=fc_calculator,
            produce_fc=True,
            symmetrize_fc=False,
            is_compact_fc=(not is_full_fc),
            log_level=log_level)
    else:
        produce_force_constants(phonon,
                                settings,
                                phpy_yaml,
                                unitcell_filename,
                                log_level)

    # Impose cutoff radius on force constants
    cutoff_radius = settings.get_cutoff_radius()
    if cutoff_radius:
        phonon.set_force_constants_zero_with_radius(cutoff_radius)

    # Enforce space group symmetry to force constants
    if settings.get_fc_spg_symmetry():
        if log_level:
            print('')
            print("Force constants are symmetrized by space group operations.")
            print("This may take some time...")
        phonon.symmetrize_force_constants_by_space_group()
        write_FORCE_CONSTANTS(phonon.get_force_constants(),
                              filename='FORCE_CONSTANTS_SPG')
        if log_level:
            print("Symmetrized force constants are written into "
                  "\"FORCE_CONSTANTS_SPG\".")

    # Imporse translational invariance and index permulation symmetry to
    # force constants
    if settings.get_fc_symmetry():
        phonon.symmetrize_force_constants()

    # Write FORCE_CONSTANTS
    if settings.get_write_force_constants():
        if settings.get_is_hdf5() or settings.get_writefc_format() == 'hdf5':
            fc_unit = physical_units['force_constants_unit']
            write_force_constants_to_hdf5(
                phonon.get_force_constants(),
                p2s_map=p2s_map,
                physical_unit=fc_unit,
                compression=settings.get_hdf5_compression())
            if log_level:
                print("Force constants are written into "
                      "\"force_constants.hdf5\".")
        else:
            fc = phonon.force_constants
            write_FORCE_CONSTANTS(fc, p2s_map=p2s_map)
            if log_level:
                print("Force constants are written into \"FORCE_CONSTANTS\".")
                print("  Array shape of force constants is %s."
                      % str(fc.shape))
                if fc.shape[0] != fc.shape[1]:
                    print("  Use --full-fc option for full array of force "
                          "constants.")

    # Show the rotational invariance condition (just show!)
    if settings.get_is_rotational_invariance():
        phonon.get_rotational_condition_of_fc()

    if log_level:
        print("")


def store_nac_params(phonon,
                     settings,
                     phpy_yaml,
                     unitcell_filename,
                     log_level,
                     nac_factor=None,
                     load_phonopy_yaml=False):
    if nac_factor is None:
        physical_units = get_default_physical_units(phonon.calculator)
        _nac_factor = physical_units['nac_factor']
    else:
        _nac_factor = nac_factor

    if settings.get_is_nac():
        def read_BORN(phonon):
            with open("BORN") as f:
                return get_born_parameters(
                    f, phonon.primitive, phonon.primitive_symmetry)

        nac_params = None

        if load_phonopy_yaml:
            nac_params = get_nac_params(primitive=phonon.primitive,
                                        nac_params=phpy_yaml.nac_params,
                                        log_level=log_level)
        else:
            if phpy_yaml:
                nac_params = phpy_yaml.nac_params
                if log_level:
                    if nac_params is None:
                        print("NAC parameters were not found in \"%s\"."
                              % unitcell_filename)
                    else:
                        print("NAC parameters were read from \"%s\"."
                              % unitcell_filename)

            if nac_params is None and file_exists("BORN", log_level):
                nac_params = read_BORN(phonon)
                if nac_params is not None and log_level:
                    print("NAC parameters were read from \"%s\"." % "BORN")

                if not nac_params:
                    error_text = "BORN file could not be read correctly."
                    print_error_message(error_text)
                    if log_level:
                        print_error()
                    sys.exit(1)

        if nac_params is not None:
            if nac_params['factor'] is None:
                nac_params['factor'] = _nac_factor
            if settings.get_nac_method() is not None:
                nac_params['method'] = settings.get_nac_method()
            phonon.nac_params = nac_params
            if log_level:
                dm = phonon.dynamical_matrix
                if dm is not None:
                    if dm.is_nac() and dm.nac_method == 'gonze':
                        dm.show_Gonze_nac_message()
                    print("")

            if log_level > 1:
                print("-" * 27 + " Dielectric constant " + "-" * 28)
                for v in nac_params['dielectric']:
                    print("         %12.7f %12.7f %12.7f" % tuple(v))
                print("-" * 26 + " Born effective charges " + "-" * 26)
                symbols = phonon.primitive.symbols
                for i, (z, s) in enumerate(zip(nac_params['born'], symbols)):
                    for j, v in enumerate(z):
                        if j == 0:
                            text = "%5d %-2s" % (i + 1, s)
                        else:
                            text = "        "
                        print("%s %12.7f %12.7f %12.7f" % ((text,) + tuple(v)))
                print("-" * 76)


def run(phonon, settings, plot_conf, log_level):
    interface_mode = phonon.calculator
    physical_units = get_default_physical_units(interface_mode)
    run_mode = settings.get_run_mode()

    #
    # QPOINTS mode
    #
    if run_mode == 'qpoints':
        if settings.get_read_qpoints():
            q_points = parse_QPOINTS()
            if log_level:
                print("Frequencies at q-points given by QPOINTS:")
        elif settings.get_qpoints():
            q_points = settings.get_qpoints()
            if log_level:
                print("Q-points that will be calculated at:")
                for q in q_points:
                    print("    %s" % q)
        else:
            print_error_message("Q-points are not properly specified.")
            if log_level:
                print_error()
            sys.exit(1)
        phonon.run_qpoints(
            q_points,
            with_eigenvectors=settings.get_is_eigenvectors(),
            with_group_velocities=settings.get_is_group_velocity(),
            with_dynamical_matrices=settings.get_write_dynamical_matrices(),
            nac_q_direction=settings.get_nac_q_direction())

        if settings.get_is_hdf5() or settings.get_qpoints_format() == "hdf5":
            phonon.write_hdf5_qpoints_phonon()
        else:
            phonon.write_yaml_qpoints_phonon()

    #
    # Band structure
    #
    if run_mode == 'band' or run_mode == 'band_mesh':
        if settings.get_band_points() is None:
            npoints = 51
        else:
            npoints = settings.get_band_points()
        band_paths = settings.get_band_paths()

        if is_band_auto(settings):
            print("SeeK-path is used to generate band paths.")
            print("  About SeeK-path https://seekpath.readthedocs.io/ "
                  "(citation there-in)")
            is_legacy_plot = False
            bands, labels, path_connections = get_band_qpoints_by_seekpath(
                phonon.primitive, npoints,
                is_const_interval=settings.get_is_band_const_interval())
        else:
            is_legacy_plot = settings.get_is_legacy_plot()
            if settings.get_is_band_const_interval():
                reclat = np.linalg.inv(phonon.primitive.cell)
                bands = get_band_qpoints(band_paths, npoints=npoints,
                                         rec_lattice=reclat)
            else:
                bands = get_band_qpoints(band_paths, npoints=npoints)
            path_connections = []
            for paths in band_paths:
                path_connections += [True, ] * (len(paths) - 2)
                path_connections.append(False)
            labels = settings.get_band_labels()

        if log_level:
            print("Reciprocal space paths in reduced coordinates:")
            for band in bands:
                print("[%6.3f %6.3f %6.3f] --> [%6.3f %6.3f %6.3f]" %
                      (tuple(band[0]) + tuple(band[-1])))

        phonon.run_band_structure(
            bands,
            with_eigenvectors=settings.get_is_eigenvectors(),
            with_group_velocities=settings.get_is_group_velocity(),
            is_band_connection=settings.get_is_band_connection(),
            path_connections=path_connections,
            labels=labels,
            is_legacy_plot=is_legacy_plot)
        if interface_mode is None:
            comment = None
        else:
            comment = {'calculator': interface_mode,
                       'length_unit': physical_units['length_unit']}

        if settings.get_is_hdf5() or settings.get_band_format() == 'hdf5':
            phonon.write_hdf5_band_structure(comment=comment)
        else:
            phonon.write_yaml_band_structure(comment=comment)

        if plot_conf['plot_graph'] and run_mode != 'band_mesh':
            plot = phonon.plot_band_structure()
            if plot_conf['save_graph']:
                plot.savefig('band.pdf')
            else:
                plot.show()

    #
    # mesh sampling
    #
    if run_mode == 'mesh' or run_mode == 'band_mesh':
        mesh_numbers = settings.get_mesh_numbers()
        if mesh_numbers is None:
            mesh_numbers = 50.0
        mesh_shift = settings.get_mesh_shift()
        t_symmetry = settings.get_time_reversal_symmetry()
        q_symmetry = settings.get_is_mesh_symmetry()
        is_gamma_center = settings.get_is_gamma_center()

        if (settings.get_is_thermal_displacements() or
            settings.get_is_thermal_displacement_matrices()):
            if settings.get_cutoff_frequency() is not None:
                if log_level:
                    print_error_message(
                        "Use FMIN (--fmin) instead of CUTOFF_FREQUENCY "
                        "(--cutoff-freq).")
                    print_error()
                sys.exit(1)

            phonon.init_mesh(mesh=mesh_numbers,
                             shift=mesh_shift,
                             is_time_reversal=t_symmetry,
                             is_mesh_symmetry=q_symmetry,
                             with_eigenvectors=settings.get_is_eigenvectors(),
                             is_gamma_center=is_gamma_center,
                             use_iter_mesh=True)
            if log_level:
                print("Mesh numbers: %s" % phonon.mesh_numbers)
        else:
            phonon.init_mesh(
                mesh=mesh_numbers,
                shift=mesh_shift,
                is_time_reversal=t_symmetry,
                is_mesh_symmetry=q_symmetry,
                with_eigenvectors=settings.get_is_eigenvectors(),
                with_group_velocities=settings.get_is_group_velocity(),
                is_gamma_center=is_gamma_center)
            if log_level:
                print("Mesh numbers: %s" % phonon.mesh_numbers)
                weights = phonon.mesh.weights
                if q_symmetry:
                    print(
                        "Number of irreducible q-points on sampling mesh: "
                        "%d/%d" % (weights.shape[0],
                                   np.prod(phonon.mesh_numbers)))
                else:
                    print("Number of q-points on sampling mesh: %d" %
                          weights.shape[0])
                print("Calculating phonons on sampling mesh...")

            phonon.mesh.run()

            if settings.get_write_mesh():
                if (settings.get_is_hdf5() or
                    settings.get_mesh_format() == 'hdf5'):
                    phonon.write_hdf5_mesh()
                else:
                    phonon.write_yaml_mesh()

        #
        # Thermal property
        #
        if settings.get_is_thermal_properties():

            if log_level:
                if settings.get_is_projected_thermal_properties():
                    print("Calculating projected thermal properties...")
                else:
                    print("Calculating thermal properties...")
            t_step = settings.get_temperature_step()
            t_max = settings.get_max_temperature()
            t_min = settings.get_min_temperature()
            phonon.run_thermal_properties(
                t_min=t_min,
                t_max=t_max,
                t_step=t_step,
                is_projection=settings.get_is_projected_thermal_properties(),
                band_indices=settings.get_band_indices(),
                cutoff_frequency=settings.get_cutoff_frequency(),
                pretend_real=settings.get_pretend_real())
            phonon.write_yaml_thermal_properties()

            if log_level:
                print("#%11s %15s%15s%15s%15s" % ('T [K]',
                                                  'F [kJ/mol]',
                                                  'S [J/K/mol]',
                                                  'C_v [J/K/mol]',
                                                  'E [kJ/mol]'))
                tp = phonon.get_thermal_properties_dict()
                temps = tp['temperatures']
                fe = tp['free_energy']
                entropy = tp['entropy']
                heat_capacity = tp['heat_capacity']
                for T, F, S, CV in zip(temps, fe, entropy, heat_capacity):
                    print(("%12.3f " + "%15.7f" * 4) %
                          (T, F, S, CV, F + T * S / 1000))

            if plot_conf['plot_graph']:
                plot = phonon.plot_thermal_properties()
                if plot_conf['save_graph']:
                    plot.savefig('thermal_properties.pdf')
                else:
                    plot.show()

        #
        # Thermal displacements
        #
        elif (settings.get_is_thermal_displacements() and
              run_mode in ('mesh', 'band_mesh')):
            p_direction = settings.get_projection_direction()
            if log_level and p_direction is not None:
                c_direction = np.dot(p_direction, phonon.primitive.cell)
                c_direction /= np.linalg.norm(c_direction)
                print("Projection direction: [%6.3f %6.3f %6.3f] "
                      "(fractional)" % tuple(p_direction))
                print("                      [%6.3f %6.3f %6.3f] "
                      "(Cartesian)" % tuple(c_direction))
            if log_level:
                print("Calculating thermal displacements...")
            t_step = settings.get_temperature_step()
            t_max = settings.get_max_temperature()
            t_min = settings.get_min_temperature()
            phonon.run_thermal_displacements(
                t_min=t_min,
                t_max=t_max,
                t_step=t_step,
                direction=p_direction,
                freq_min=settings.get_min_frequency(),
                freq_max=settings.get_max_frequency())
            phonon.write_yaml_thermal_displacements()

            if plot_conf['plot_graph']:
                plot = phonon.plot_thermal_displacements(
                    plot_conf['with_legend'])
                if plot_conf['save_graph']:
                    plot.savefig('thermal_displacement.pdf')
                else:
                    plot.show()

        #
        # Thermal displacement matrices
        #
        elif (settings.get_is_thermal_displacement_matrices() and
              run_mode in ('mesh', 'band_mesh')):
            if log_level:
                print("Calculating thermal displacement matrices...")
            t_step = settings.get_temperature_step()
            t_max = settings.get_max_temperature()
            t_min = settings.get_min_temperature()
            t_cif = settings.get_thermal_displacement_matrix_temperature()
            if t_cif is None:
                temperatures = None
            else:
                temperatures = [t_cif, ]
            phonon.run_thermal_displacement_matrices(
                t_step=t_step,
                t_max=t_max,
                t_min=t_min,
                temperatures=temperatures,
                freq_min=settings.get_min_frequency(),
                freq_max=settings.get_max_frequency())
            phonon.write_yaml_thermal_displacement_matrices()
            if t_cif is not None:
                phonon.write_thermal_displacement_matrix_to_cif(0)

        #
        # Projected DOS
        #
        elif (settings.get_pdos_indices() is not None and
              run_mode in ('mesh', 'band_mesh')):
            p_direction = settings.get_projection_direction()
            if (log_level and
                p_direction is not None and
                not settings.get_xyz_projection()):
                c_direction = np.dot(p_direction, phonon.primitive.cell)
                c_direction /= np.linalg.norm(c_direction)
                print("Projection direction: [%6.3f %6.3f %6.3f] "
                      "(fractional)" % tuple(p_direction))
                print("                      [%6.3f %6.3f %6.3f] "
                      "(Cartesian)" % tuple(c_direction))
            if log_level:
                print("Calculating projected DOS...")

            phonon.run_projected_dos(
                sigma=settings.get_sigma(),
                freq_min=settings.get_min_frequency(),
                freq_max=settings.get_max_frequency(),
                freq_pitch=settings.get_frequency_pitch(),
                use_tetrahedron_method=settings.get_is_tetrahedron_method(),
                direction=p_direction,
                xyz_projection=settings.get_xyz_projection())
            phonon.write_projected_dos()

            if plot_conf['plot_graph']:
                pdos_indices = settings.get_pdos_indices()
                if is_pdos_auto(settings):
                    pdos_indices = get_pdos_indices(
                        phonon.primitive_symmetry)
                    legend = [phonon.primitive.symbols[x[0]]
                              for x in pdos_indices]
                else:
                    legend = [np.array(x) + 1 for x in pdos_indices]
                if run_mode != 'band_mesh':
                    plot = phonon.plot_projected_dos(
                        pdos_indices=pdos_indices,
                        legend=legend)
                    if plot_conf['save_graph']:
                        plot.savefig('partial_dos.pdf')
                    else:
                        plot.show()

        #
        # Total DOS
        #
        elif ((plot_conf['plot_graph'] or settings.get_is_dos_mode()) and
              not is_pdos_auto(settings) and
              run_mode in ('mesh', 'band_mesh')):
            phonon.run_total_dos(
                sigma=settings.get_sigma(),
                freq_min=settings.get_min_frequency(),
                freq_max=settings.get_max_frequency(),
                freq_pitch=settings.get_frequency_pitch(),
                use_tetrahedron_method=settings.get_is_tetrahedron_method())

            if log_level:
                print("Calculating DOS...")

            if settings.get_fits_Debye_model():
                phonon.set_Debye_frequency()
                if log_level:
                    debye_freq = phonon.get_Debye_frequency()
                    print("Debye frequency: %10.5f" % debye_freq)
            phonon.write_total_dos()

            if plot_conf['plot_graph'] and run_mode != 'band_mesh':
                plot = phonon.plot_total_dos()
                if plot_conf['save_graph']:
                    plot.savefig('total_dos.pdf')
                else:
                    plot.show()

        #
        # Momemt
        #
        elif (settings.get_is_moment() and run_mode in ('mesh', 'band_mesh')):
            freq_min = settings.get_min_frequency()
            freq_max = settings.get_max_frequency()
            if log_level:
                text = "Calculating moment of phonon states distribution"
                if freq_min is None and freq_max is None:
                    text += "..."
                elif freq_min is None and freq_max is not None:
                    text += "\nbelow frequency %.3f..." % freq_max
                elif freq_min is not None and freq_max is None:
                    text += "\nabove frequency %.3f..." % freq_min
                elif freq_min is not None and freq_max is not None:
                    text += ("\nbetween frequencies %.3f and %.3f..." %
                             (freq_min, freq_max))
            print(text)
            print('')
            print("Order|   Total   |   Projected to atoms")
            if settings.get_moment_order() is not None:
                phonon.run_moment(order=settings.get_moment_order(),
                                  freq_min=freq_min,
                                  freq_max=freq_max,
                                  is_projection=False)
                total_moment = phonon.get_moment()
                phonon.run_moment(order=settings.get_moment_order(),
                                  freq_min=freq_min,
                                  freq_max=freq_max,
                                  is_projection=True)
                text = " %3d |%10.5f | " % (settings.get_moment_order(),
                                            total_moment)
                for m in phonon.get_moment():
                    text += "%10.5f " % m
                print(text)
            else:
                for i in range(3):
                    phonon.run_moment(order=i,
                                      freq_min=freq_min,
                                      freq_max=freq_max,
                                      is_projection=False)
                    total_moment = phonon.get_moment()
                    phonon.run_moment(order=i,
                                      freq_min=freq_min,
                                      freq_max=freq_max,
                                      is_projection=True)
                    text = " %3d |%10.5f | " % (i, total_moment)
                    for m in phonon.get_moment():
                        text += "%10.5f " % m
                    print(text)

        #
        # Band structure and DOS are plotted simultaneously.
        #
        if (run_mode == 'band_mesh' and
            plot_conf['plot_graph'] and
            not settings.get_is_thermal_properties() and
            not settings.get_is_thermal_displacements() and
            not settings.get_is_thermal_displacement_matrices() and
            not settings.get_is_thermal_distances()):
            if settings.get_pdos_indices() is not None:
                plot = phonon.plot_band_structure_and_dos(
                    pdos_indices=pdos_indices)
            else:
                plot = phonon.plot_band_structure_and_dos()
            if plot_conf['save_graph']:
                plot.savefig('band_dos.pdf')
            else:
                plot.show()

    #
    # Animation
    #
    elif run_mode == 'anime':
        anime_type = settings.get_anime_type()
        if anime_type == "v_sim":
            q_point = settings.get_anime_qpoint()
            amplitude = settings.get_anime_amplitude()
            phonon.write_animation(q_point=q_point,
                                   anime_type='v_sim',
                                   amplitude=amplitude)
            if log_level:
                print("Animation type: v_sim")
                print("q-point: [%6.3f %6.3f %6.3f]" % tuple(q_point))
        else:
            amplitude = settings.get_anime_amplitude()
            band_index = settings.get_anime_band_index()
            division = settings.get_anime_division()
            shift = settings.get_anime_shift()
            phonon.write_animation(anime_type=anime_type,
                                   band_index=band_index,
                                   amplitude=amplitude,
                                   num_div=division,
                                   shift=shift)

            if log_level:
                print("Animation type: %s" % anime_type)
                print("amplitude: %f" % amplitude)
                if anime_type != "jmol":
                    print("band index: %d" % band_index)
                    print("Number of images: %d" % division)

    #
    # Modulation
    #
    elif run_mode == 'modulation':
        mod_setting = settings.get_modulation()
        phonon_modes = mod_setting['modulations']
        dimension = mod_setting['dimension']
        if 'delta_q' in mod_setting:
            delta_q = mod_setting['delta_q']
        else:
            delta_q = None
        derivative_order = mod_setting['order']
        num_band = len(phonon.primitive) * 3

        if log_level:
            if len(phonon_modes) == 1:
                print("Modulated structure with %s multiplicity was created."
                      % dimension)
            else:
                print("Modulated structures with %s multiplicity were created."
                      % dimension)

        error_indices = []
        for i, ph_mode in enumerate(phonon_modes):
            if ph_mode[1] < 0 or ph_mode[1] >= num_band:
                error_indices.append(i)
            if log_level:
                text = ("%d: q%s, band index=%d, amplitude=%f"
                        % (i + 1, ph_mode[0], ph_mode[1] + 1, ph_mode[2]))
                if len(ph_mode) > 3:
                    text += ", phase=%f" % ph_mode[3]
                print(text)

        if error_indices:
            if log_level:
                lines = ["Band index of modulation %d is out of range."
                         % (i + 1) for i in error_indices]
                print_error_message('\n'.join(lines))
            print_error()
            sys.exit(1)

        phonon.set_modulations(dimension,
                               phonon_modes,
                               delta_q=delta_q,
                               derivative_order=derivative_order,
                               nac_q_direction=settings.get_nac_q_direction())
        phonon.write_modulations()
        phonon.write_yaml_modulations()

    #
    # Ir-representation
    #
    elif run_mode == 'irreps':
        if phonon.set_irreps(
                settings.get_irreps_q_point(),
                is_little_cogroup=settings.get_is_little_cogroup(),
                nac_q_direction=settings.get_nac_q_direction(),
                degeneracy_tolerance=settings.get_irreps_tolerance()):
            show_irreps = settings.get_show_irreps()
            phonon.show_irreps(show_irreps)
            phonon.write_yaml_irreps(show_irreps)


def start_phonopy(**argparse_control):
    """Parse arguments and set some basic parameters"""

    parser, deprecated = get_parser(**argparse_control)
    args = parser.parse_args()

    # Set log level
    log_level = 1
    if args.verbose:
        log_level = 2
    if args.quiet or args.is_check_symmetry:
        log_level = 0
    if args.loglevel is not None:
        log_level = args.loglevel

    if args.is_graph_save:
        import matplotlib
        matplotlib.use('Agg')

    # Show phonopy logo
    if log_level:
        print_phonopy()
        print_version(__version__)
        if argparse_control.get('load_phonopy_yaml', False):
            print("Running in phonopy.load mode.")
        print("Python version %d.%d.%d" % sys.version_info[:3])
        import phonopy.structure.spglib as spglib
        print("Spglib version %d.%d.%d" % spglib.get_version())
        print("")

        if deprecated:
            show_deprecated_option_warnings(deprecated)

    return (args, log_level,
            {'plot_graph': args.is_graph_plot,
             'save_graph': args.is_graph_save,
             'with_legend': args.is_legend})


def create_phonopy_files_then_exit(args, log_level):
    """Integrated helper tools"""

    # Create FORCE_SETS (-f or --force_sets)
    if args.force_sets or args.force_sets_zero:
        create_FORCE_SETS_from_args(args, log_level)

    # Create FORCE_CONSTANTS (--fc or --force_constants)
    if args.force_constants:
        filename = args.force_constants[0]
        file_exists(filename, log_level)
        write_hdf5 = (args.is_hdf5 or
                      args.fc_format == 'hdf5' or
                      args.writefc_format == 'hdf5')
        error_num = create_FORCE_CONSTANTS(filename, write_hdf5, log_level)
        if log_level:
            print_end()
        sys.exit(error_num)


def read_phonopy_settings(args, argparse_control, log_level):
    """Read phonopy settings"""

    load_phonopy_yaml = argparse_control.get('load_phonopy_yaml', False)

    if len(args.filename) > 0:
        file_exists(args.filename[0], log_level)
        if load_phonopy_yaml:
            phonopy_conf_parser = PhonopyConfParser(
                args=args, default_settings=argparse_control)
            cell_filename = args.filename[0]
        else:
            if is_file_phonopy_yaml(args.filename[0]):
                phonopy_conf_parser = PhonopyConfParser(args=args)
                cell_filename = args.filename[0]
            else:
                phonopy_conf_parser = PhonopyConfParser(
                    filename=args.filename[0], args=args)
                cell_filename = phonopy_conf_parser.settings.cell_filename
    else:
        phonopy_conf_parser = PhonopyConfParser(args=args)
        cell_filename = phonopy_conf_parser.settings.cell_filename

    confs = phonopy_conf_parser.confs.copy()
    settings = phonopy_conf_parser.settings

    return settings, confs, cell_filename


def is_band_auto(settings):
    return (type(settings.get_band_paths()) is str and
            settings.get_band_paths() == 'auto')


def is_pdos_auto(settings):
    return (settings.get_pdos_indices() == 'auto')


def auto_primitive_axes(primitive_matrix):
    return (type(primitive_matrix) is str and primitive_matrix == 'auto')


def get_fc_calculator_params(settings):
    fc_calculator = None
    if settings.get_fc_calculator() is not None:
        if settings.get_fc_calculator().lower() in fc_calculator_names:
            fc_calculator = settings.get_fc_calculator().lower()

    fc_calculator_options = None
    if settings.get_fc_calculator_options() is not None:
        fc_calculator_options = settings.get_fc_calculator_options()

    return fc_calculator, fc_calculator_options


def get_cell_info(settings, cell_filename, symprec, log_level):
    """calculator interface and crystal structure information"""

    cell_info = collect_cell_info(
        supercell_matrix=settings.get_supercell_matrix(),
        primitive_matrix=settings.get_primitive_matrix(),
        interface_mode=settings.get_calculator(),
        cell_filename=cell_filename,
        chemical_symbols=settings.get_chemical_symbols(),
        enforce_primitive_matrix_auto=is_band_auto(settings),
        symprec=symprec,
        return_dict=True)
    if type(cell_info) is str:
        print_error_message(cell_info)
        if log_level:
            print_error()
        sys.exit(1)

    # (unitcell, supercell_matrix, primitive_matrix,
    #  optional_structure_info, interface_mode,
    #  phpy_yaml) = cell_info
    # unitcell_filename = optional_structure_info[0]

    # Set magnetic moments
    magmoms = settings.get_magnetic_moments()
    if magmoms is not None:
        unitcell = cell_info['unitcell']
        if len(magmoms) == len(unitcell):
            unitcell.magnetic_moments = magmoms
        else:
            error_text = "Invalid MAGMOM setting"
            print_error_message(error_text)
            if log_level:
                print_error()
            sys.exit(1)

        if auto_primitive_axes(cell_info['primitive_matrix']):
            error_text = ("'PRIMITIVE_AXES = auto', 'BAND = auto', or no DIM "
                          "setting is not allowed with MAGMOM.")
            print_error_message(error_text)
            if log_level:
                print_error()
            sys.exit(1)

    cell_info['magmoms'] = magmoms

    return cell_info


def show_symmetry_info_then_exit(cell_info, symprec):
    """Show crystal structure information in yaml style."""
    phonon = Phonopy(cell_info['unitcell'],
                     np.eye(3, dtype=int),
                     primitive_matrix=cell_info['primitive_matrix'],
                     symprec=symprec,
                     calculator=cell_info['interface_mode'],
                     log_level=0)
    check_symmetry(phonon, cell_info['optional_structure_info'])
    sys.exit(0)


def init_phonopy(settings, cell_info, symprec, log_level):
    # Prepare phonopy object
    if (settings.get_create_displacements() and
        settings.get_temperatures() is None):
        phonon = Phonopy(cell_info['unitcell'],
                         cell_info['supercell_matrix'],
                         primitive_matrix=cell_info['primitive_matrix'],
                         symprec=symprec,
                         is_symmetry=settings.get_is_symmetry(),
                         calculator=cell_info['interface_mode'],
                         log_level=log_level)
    else:  # Read FORCE_SETS, FORCE_CONSTANTS, or force_constants.hdf5
        # Overwrite frequency unit conversion factor
        if settings.get_frequency_conversion_factor() is not None:
            freq_factor = settings.get_frequency_conversion_factor()
        else:
            physical_units = get_default_physical_units(
                cell_info['interface_mode'])
            freq_factor = physical_units['factor']

        phonon = Phonopy(
            cell_info['unitcell'],
            cell_info['supercell_matrix'],
            primitive_matrix=cell_info['primitive_matrix'],
            factor=freq_factor,
            frequency_scale_factor=settings.get_frequency_scale_factor(),
            dynamical_matrix_decimals=settings.get_dm_decimals(),
            force_constants_decimals=settings.get_fc_decimals(),
            group_velocity_delta_q=settings.get_group_velocity_delta_q(),
            symprec=symprec,
            is_symmetry=settings.get_is_symmetry(),
            calculator=cell_info['interface_mode'],
            use_lapack_solver=settings.get_lapack_solver(),
            log_level=log_level)

    # Set atomic masses of primitive cell
    if settings.get_masses() is not None:
        phonon.masses = settings.get_masses()

    # Atomic species without mass case
    symbols_with_no_mass = []
    if phonon.primitive.masses is None:
        for s in phonon.primitive.symbols:
            if (atom_data[symbol_map[s]][3] is None and
                s not in symbols_with_no_mass):
                symbols_with_no_mass.append(s)
                print_error_message(
                    "Atomic mass of \'%s\' is not implemented in phonopy." % s)
                print_error_message(
                    "MASS tag can be used to set atomic masses.")

    if len(symbols_with_no_mass) > 0:
        if log_level:
            print_end()
        sys.exit(1)

    return phonon


def main(**argparse_control):
    ############################################
    # Parse phonopy conf and crystal structure #
    ############################################
    load_phonopy_yaml = argparse_control.get('load_phonopy_yaml', False)

    args, log_level, plot_conf = start_phonopy(**argparse_control)

    # Phonopy utils to create FORCE_SETS and FORCE_CONSTANTS
    create_phonopy_files_then_exit(args, log_level)

    settings, confs, cell_filename = read_phonopy_settings(
        args, argparse_control, log_level)

    run_symmetry_info = args.is_check_symmetry

    # Symmetry tolerance. Distance unit depends on interface.
    if settings.get_symmetry_tolerance() is None:
        symprec = 1e-5
    else:
        symprec = settings.get_symmetry_tolerance()

    # Here optionally phonopy.yaml like file is parsed.
    cell_info = get_cell_info(settings, cell_filename, symprec, log_level)
    unitcell_filename = cell_info['optional_structure_info'][0]

    # -----------------------------------------------------------------------
    # ----------------- 'args' should not be used below. --------------------
    # -----------------------------------------------------------------------

    ###########################################################
    # Show crystal symmetry information and exit (--symmetry) #
    ###########################################################
    if run_symmetry_info:
        show_symmetry_info_then_exit(cell_info, symprec)

    ######################
    # Initialize phonopy #
    ######################
    phonon = init_phonopy(settings, cell_info, symprec, log_level)

    ################################################
    # Show phonopy settings and crystal structures #
    ################################################
    if log_level:
        print_settings(settings,
                       phonon,
                       auto_primitive_axes(cell_info['primitive_matrix']),
                       unitcell_filename,
                       load_phonopy_yaml)
        if cell_info['magmoms'] is None:
            print("Spacegroup: %s" %
                  phonon.get_symmetry().get_international_table())
        if log_level > 1:
            print_cells(phonon, unitcell_filename)
        else:
            print("Use -v option to watch primitive cell, unit cell, "
                  "and supercell structures.")
        if log_level == 1:
            print("")

    #########################################################
    # Create constant amplitude displacements and then exit #
    #########################################################
    if (settings.get_create_displacements() and
        settings.get_temperatures() is None):
        if settings.get_displacement_distance() is None:
            displacement_distance = get_default_displacement_distance(
                phonon.calculator)
        else:
            displacement_distance = settings.get_displacement_distance()
        phonon.generate_displacements(
            distance=displacement_distance,
            is_plusminus=settings.get_is_plusminus_displacement(),
            is_diagonal=settings.get_is_diagonal_displacement(),
            is_trigonal=settings.get_is_trigonal_displacement(),
            number_of_snapshots=settings.get_random_displacements(),
            random_seed=settings.get_random_seed())
        write_displacements_files_then_exit(
            phonon,
            settings,
            confs,
            cell_info['optional_structure_info'],
            log_level)

    ###################
    # Force constants #
    ###################
    store_force_constants(phonon,
                          settings,
                          cell_info['phonopy_yaml'],
                          unitcell_filename,
                          load_phonopy_yaml,
                          log_level)

    ##################################
    # Non-analytical term correction #
    ##################################
    store_nac_params(phonon,
                     settings,
                     cell_info['phonopy_yaml'],
                     unitcell_filename,
                     log_level,
                     load_phonopy_yaml=load_phonopy_yaml)

    ###################################################################
    # Create random displacements at finite temperature and then exit #
    ###################################################################
    if (settings.get_create_displacements() and
        settings.get_temperatures() is not None):
        phonon.generate_displacements(
            number_of_snapshots=settings.get_random_displacements(),
            random_seed=settings.get_random_seed(),
            temperature=settings.get_temperatures()[0])
        write_displacements_files_then_exit(
            phonon,
            settings,
            confs,
            cell_info['optional_structure_info'],
            log_level)

    #######################
    # Phonon calculations #
    #######################
    if settings.get_run_mode() not in ('band', 'mesh', 'band_mesh', 'anime',
                                       'modulation', 'irreps', 'qpoints'):
        print("-" * 76)
        print(" One of the following run modes may be specified for phonon "
              "calculations.")
        for mode in ['Mesh sampling (MESH, --mesh)',
                     'Q-points (QPOINTS, --qpoints)',
                     'Band structure (BAND, --band)',
                     'Animation (ANIME, --anime)',
                     'Modulation (MODULATION, --modulation)',
                     'Characters of Irreps (IRREPS, --irreps)',
                     'Create displacements (CREATE_DISPLACEMENTS, -d)']:
            print(" - %s" % mode)
        print("-" * 76)

    run(phonon, settings, plot_conf, log_level)

    ########################
    # Phonopy finalization #
    ########################
    finalize_phonopy(log_level, settings, confs, phonon)

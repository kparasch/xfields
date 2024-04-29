# copyright ################################# #
# This file is part of the Xfields Package.   #
# Copyright (c) CERN, 2021.                   #
# ########################################### #

from __future__ import annotations  # important for sphinx to alias ArrayLike

from logging import getLogger
from typing import Tuple

import numpy as np
import xobjects as xo
import xtrack as xt
from numpy.typing import ArrayLike
from scipy.constants import c
from scipy.special import elliprd

from xfields.ibs._analytical import BjorkenMtingwaIBS, IBSGrowthRates
from xfields.ibs._formulary import (
    _assert_accepted_context,
    _beam_intensity,
    _bunch_length,
    _current_turn,
    _gemitt_x,
    _gemitt_y,
    _sigma_delta,
    _sigma_px,
    _sigma_py,
    _sigma_x,
    _sigma_y,
    phi,
)

LOGGER = getLogger(__name__)


# ----- Some classes to store results (as xo.HybridClass) ----- #


class DiffusionCoefficients(xo.HybridClass):
    """
    Holds the diffusion coefficients, named ``Dx``,
    ``Dy``, and ``Dz``, which are computed in the
    kinetic kick formalism.

    Attributes:
    -----------
    Dx : float
        Horizontal diffusion coefficient.
    Dy : float
        Vertical diffusion coefficient.
    Dz : float
        Longitudinal diffusion coefficient.
    """

    _xofields = {
        "Dx": xo.Float64,
        "Dy": xo.Float64,
        "Dz": xo.Float64,
    }

    def __init__(self, Dx: float, Dy: float, Dz: float) -> None:
        """Init by providing the diffusion coefficients."""
        self.xoinitialize(Dx=Dx, Dy=Dy, Dz=Dz)

    def as_tuple(self) -> Tuple[float, float, float]:
        """Return the growth rates as a tuple."""
        return float(self.Dx), float(self.Dy), float(self.Dz)


class FrictionCoefficients(xo.HybridClass):
    """
    Holds the friction coefficients, named ``Fx``,
    ``Fy``, and ``Fz``, which are computed in the
    kinetic kick formalism.

    Attributes:
    -----------
    Fx : float
        Horizontal friction coefficient.
    Fy : float
        Vertical friction coefficient.
    Fz : float
        Longitudinal friction coefficient.
    """

    _xofields = {
        "Fx": xo.Float64,
        "Fy": xo.Float64,
        "Fz": xo.Float64,
    }

    def __init__(self, Fx: float, Fy: float, Fz: float) -> None:
        """Init by providing the friction coefficients."""
        self.xoinitialize(Fx=Fx, Fy=Fy, Fz=Fz)

    def as_tuple(self) -> Tuple[float, float, float]:
        """Return the growth rates as a tuple."""
        return float(self.Fx), float(self.Fy), float(self.Fz)


class IBSKickCoefficients(xo.HybridClass):
    """
    Holds the kick coefficients, named ``Kx``,
    ``Ky``, and ``Kz``, which are used in order
    to determine the applied momenta kicks.

    Attributes:
    -----------
    Kx : float
        Horizontal kick coefficient.
    Ky : float
        Vertical kick coefficient.
    Kz : float
        Longitudinal kick coefficient.
    """

    _xofields = {
        "Kx": xo.Float64,
        "Ky": xo.Float64,
        "Kz": xo.Float64,
    }

    def __init__(self, Kx: float, Ky: float, Kz: float) -> None:
        """Init by providing the kick coefficients."""
        self.xoinitialize(Kx=Kx, Ky=Ky, Kz=Kz)

    def as_tuple(self) -> Tuple[float, float, float]:
        """Return the growth rates as a tuple."""
        return float(self.Kx), float(self.Ky), float(self.Kz)


# ----- Useful Functions ----- #


# TODO: someday replace this with what Gianni is working on in xfields.longitudinal_profiles
def line_density(particles: xt.Particles, num_slices: int) -> ArrayLike:
    """
    Returns the longitudinal "line density" of the provided `xtrack.Particles`.
    It is used as a weighing factor for the application of IBS kicks, so that
    particles in the denser parts of the bunch will receive a larger kick, and
    vice versa.

    Parameters
    ----------
    particles : xtrack.Particles
        The `xtrack.Particles` object to compute the line density for.
    num_slices : int
        The number of slices to use for the computation of the bins.

    Returns
    -------
    ArrayLike
        An array with the weight value for each particle, to be used
        as a weight in the kicks application. This array is on the
        context device of the particles.
    """
    # ----------------------------------------------------------------------------------------------
    # Get the nplike_lib from the particles' context, to compute on the context device
    nplike = particles._context.nplike_lib
    # ----------------------------------------------------------------------------------------------
    # Determine properties from longitudinal particles distribution: cuts, slice width, bunch length
    LOGGER.debug("Determining longitudinal particles distribution properties")
    zeta: ArrayLike = particles.zeta[particles.state > 0]  # careful to only consider active particles
    z_cut_head: float = nplike.max(zeta)  # z cut at front of bunch
    z_cut_tail: float = nplike.min(zeta)  # z cut at back of bunch
    slice_width: float = (z_cut_head - z_cut_tail) / num_slices  # slice width
    # ----------------------------------------------------------------------------------------------
    # Determine bin edges and bin centers for the distribution
    LOGGER.debug("Determining bin edges and bin centers for the distribution")
    bin_edges: ArrayLike = nplike.linspace(
        z_cut_tail - 1e-7 * slice_width,
        z_cut_head + 1e-7 * slice_width,
        num=num_slices + 1,
        dtype=np.float64,
    )
    bin_centers: ArrayLike = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    # ----------------------------------------------------------------------------------------------
    # Compute histogram on longitudinal distribution then compute and return line density
    counts_normed, bin_edges = nplike.histogram(zeta, bin_edges, density=True)  # density to normalize
    return nplike.interp(zeta, bin_centers, counts_normed)


# ----- Parent Class to Identify the IBS Kicks ----- #


class IBSKick:
    """
    General class for IBS kicks to inherit from.
    """

    iscollective = True  # based on alive particles, need them all here

    def to_dict(self) -> None:
        """Raises an error as the line should be saved without the IBS kick element."""
        raise NotImplementedError("IBS kick elements should not be saved as part of the line")


# ----- Simple Kick Implementation ----- #


class IBSSimpleKick(IBSKick):
    r"""
    Beam element to apply IBS effects to particles during tracking according to
    the formalism introduced in :cite:`PRAB:Bruce:Simple_IBS_Kicks`. It provides
    momenta kicks based on analytical growth rates, weighted by the longitudinal
    line density of the particles and including a random component.

    The element starts off by default (will not affect particles) and has to be
    configured through the `line.configure_intrabeam_scattering` method.

    Warnings
    --------
        This formalism is only valid **above** transition energy. The implemented
        weighted random-component momentum kick depends on the square root of the
        growth rate, which is set to 0 if it is negative. Below transition it is
        common to observe negative growth rates and emittance shrinkage, which this
        kick would not be reprensentative of. A message is logged to inform the user
        when this happens. For machines below transition energy, the kinetic formalism
        should be used instead: see the `IBSKineticKick` class).

    Attributes
    ----------
    num_slices : int
        The number of slices used for the computation of the bunch's
        longitudinal line density.
    formalism : str
        The formalism used for the computation of the growth rates.
    update_every : int
        The frequency at which to recompute the kick coefficients, in
        number of turns. They will be computed at the first turn of
        tracking, and then every `update_every` turns afterwards.
    kick_coefficients : IBSKickCoefficients
        The computed kick coefficients. This self-updates when they
        are computed with the `.compute_kick_coefficients` method.
    """

    def __init__(self, formalism: str, num_slices: int) -> None:
        """
        Initialize the Simple IBS kick element. It is off
        by default and will have to be configured (see the
        line.configure_intrabeam_scattering method).

        Parameters
        ----------
        formalism : str
            Which formalism to use for the computation of the growth
            rates. Can be ``Nagaitsev`` or ``Bjorken-Mtingwa`` (also
            accepts ``B&M``), case-insensitively.
        num_slices : int
            The number of slices used for the computation of
            the bunch's longitudinal line density.
        """
        assert formalism.lower() in ("nagaitsev", "bjorken-mtingwa", "b&m")
        self.num_slices = num_slices
        self.formalism = formalism
        self.kick_coefficients: IBSKickCoefficients = None
        # The following are needed but start unset. They are set
        # when calling line.configure_intrabeam_scattering()
        self.update_every: int = None
        self._name: str = None
        self._twiss: xt.TwissTable = None
        self._scale_strength: float = 0  # by default element does not "track"

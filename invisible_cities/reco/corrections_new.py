import numpy  as np
import pandas as pd
from   pandas      import DataFrame
from   pandas      import Series
from   dataclasses import dataclass
from   typing      import Callable
from   typing      import List
from   typing      import Optional
from   enum        import auto
from .. types.ic_types  import AutoNameEnumBase
from .. evm.event_model import Hit

@dataclass
class ASectorMap:  # Map in chamber sector containing average of pars
    chi2    : DataFrame
    e0      : DataFrame
    lt      : DataFrame
    e0u     : DataFrame
    ltu     : DataFrame
    mapinfo : Optional[Series]
    t_evol  : Optional[DataFrame]

@dataclass
class FitMapValue:  # A ser of values of a FitMap
    chi2  : float
    e0    : float
    lt    : float
    e0u   : float
    ltu   : float

class MissingArgumentError(Exception):
    def __init__(self):
        s  = 'You must provide a time evolution map '
        s += 'if time correction is wanted to be applied.'
        Exception.__init__(self, s)

def amap_max(amap : ASectorMap)->FitMapValue:
    return FitMapValue(chi2 = amap.chi2.max().max(),
                       e0   = amap.e0  .max().max(),
                       lt   = amap.lt  .max().max(),
                       e0u  = amap.e0u .max().max(),
                       ltu  = amap.ltu .max().max())

def read_maps(filename : str)->ASectorMap:

    """
    Read 'filename' variable and creates ASectorMap class.
    If the map corresponds to a data run (run_number>0),
    ASectorMap will also contain a DataFrame with time evolution information.

    Parameters
    ----------
    filename : string
        Name of the file that contains the correction maps.

    Returns
    -------
    ASectorMap:

@dataclass
class ASectorMap:
    chi2    : DataFrame            # chi2 value for each bin
    e0      : DataFrame            # geometric map
    lt      : DataFrame            # lifetime map
    e0u     : DataFrame            # uncertainties of geometric map
    ltu     : DataFrame            # uncertainties of lifetime map
    mapinfo : Optional[Series]     # series with some info about the
    t_evol  : Optional[DataFrame]  # time evolution of some parameters
                                     (only for data)
    """

    chi2     = pd.read_hdf(filename, 'chi2')
    e0       = pd.read_hdf(filename, 'e0')
    e0u      = pd.read_hdf(filename, 'e0u')
    lt       = pd.read_hdf(filename, 'lt')
    ltu      = pd.read_hdf(filename, 'ltu')
    mapinfo  = pd.read_hdf(filename, 'mapinfo')

    if mapinfo.run_number>0:
        try:
            t_evol = pd.read_hdf(filename, 'time_evolution')
        except:
            t_evol = None
        maps   = ASectorMap(chi2, e0, lt, e0u, ltu, mapinfo, t_evol)

    else: maps = ASectorMap(chi2, e0, lt, e0u, ltu, mapinfo, None)

    return  maps


def maps_coefficient_getter(mapinfo : Series,
                            map_df  : DataFrame) -> Callable:
    """
    For a given correction map,
    it returns a function that yields the values of map
    for a given (X,Y) position.

    Parameters
    ----------
    mapinfo : Series
        Stores some information about the map
        (run number, number of X-Y bins, X-Y range)
    map_df : DataFrame
        DataFrame of a correction map (lt or e0)

    Returns
    -------
        A function that returns the value of the 'map_df' map
        for a given (X,Y) position
    """

    binsx   = np.linspace(mapinfo.xmin,mapinfo.xmax,mapinfo.nx+1)
    binsy   = np.linspace(mapinfo.ymin,mapinfo.ymax,mapinfo.ny+1)
    def get_maps_coefficient(x : np.array, y : np.array) -> np.array:
        ix = np.digitize(x, binsx)-1
        iy = np.digitize(y, binsy)-1
        return np.array([map_df.get(j, {}).get(i, np.nan) for i, j in zip(iy,ix)])
    return get_maps_coefficient


def correct_geometry_(CE : np.array) -> np.array:
    """
    Computes the geometric correction factor
    for a given correction coefficient

    Parameters
    ----------
    CE : np.array
        Array with geometric correction coefficients

    Returns
    -------
        An array with geometric correction factors
    """

    return 1/CE


def correct_lifetime_(Z : np.array, LT : np.array) -> np.array:
    """
    Computes the lifetime correction factor
    for a given correction coefficient

    Parameters
    ----------
    LT : np.array
        Array with lifetime correction coefficients

    Returns
    -------
        An array with lifetime correction factors
    """

    return np.exp(Z / LT)


def time_coefs_corr(time_evt   : np.array,
                    times_evol : np.array,
                    par        : np.array,
                    par_u      : np.array)-> np.array:
    """
    Computes a time-dependence parameter that will correct the
    correction coefficient for taking into account time evolution.

    Parameters
    ----------
    time_evt : np.array
        Array with timestamps for each hit (is the same for all hit of the same event).
    times_evol : np.array
        Time intervals to perform the interpolation.
    par : np.array
        Time evolution of a certain parameter (e.g. lt or e0).
        Each value is associated to a times_evol one.
    par_u : np.array
        Time evolution of the uncertainty of a certain parameter.
        Each value is associated to a times_evol one.

    Returns
    -------
        An array with the computed value.
    """

    par_mean   = np.average(par, weights=par_u)
    par_i      = np.interp(time_evt, times_evol, par)
    par_factor = par_i/par_mean
    return par_factor


def e0_xy_corrections(X : np.array, Y : np.array, maps : ASectorMap)-> np.array:
    mapinfo = maps.mapinfo
    map_df  = maps.e0
    get_maps_coefficient= maps_coefficient_getter(mapinfo, map_df)
    CE  = get_maps_coefficient(X,Y)
    return correct_geometry_(CE)

def lt_xy_corrections(X : np.array, Y : np.array, Z : np.array, maps : ASectorMap)-> np.array:
    mapinfo = maps.mapinfo
    map_df  = maps.lt
    get_maps_coefficient= maps_coefficient_getter(mapinfo, map_df)
    LT  = get_maps_coefficient(X,Y)
    return correct_lifetime_(Z,LT)

def apply_all_correction_single_maps(map_e0     : ASectorMap,
                                     map_lt     : ASectorMap,
                                     map_te     : Optional[ASectorMap] = None,
                                     apply_temp : bool                 = True) -> Callable:
    """
    For a map for each correction, it returns a function
    that provides a correction factor for a
    given hit collection when (x,y,z,time) is provided.

    Parameters
    ----------
    map_e0 : AsectorMap
        Correction map for geometric orrections.
    map_lt : AsectorMap
        Correction map for lifetime orrections.
    map_te : AsectorMap (optional)
        Correction map with time evolution of some kdst parameters.
    apply_temp : Bool
        If True, time evolution will be taken into account.

    Returns
    -------
        A function that returns time correction factor without passing a map.
    """

    if apply_temp and map_te is None:
        raise MissingArgumentError
        pass

    get_xy_corr_fun = maps_coefficient_getter(map_e0.mapinfo, map_e0.e0)
    get_lt_corr_fun = maps_coefficient_getter(map_lt.mapinfo, map_lt.lt)

    max_e0 = amap_max(map_e0).e0

    if apply_temp:
        if map_te.mapinfo.run_number>0:
            evol_table      = map_te.t_evol
            temp_correct_e0 = lambda t : time_coefs_corr(t,
                                                         evol_table.ts,
                                                         evol_table.e0,
                                                         evol_table.e0u)
            temp_correct_lt = lambda t : time_coefs_corr(t,
                                                         evol_table.ts,
                                                         evol_table['lt'],
                                                         evol_table.ltu)
            e0evol_vs_t     = temp_correct_e0
            ltevol_vs_t     = temp_correct_lt
    else:
        e0evol_vs_t = lambda x : np.ones_like(x)
        ltevol_vs_t = lambda x : np.ones_like(x)

    def total_correction_factor(x : np.array,
                                y : np.array,
                                z : np.array,
                                t : np.array)-> np.array:
        geo_factor = correct_geometry_(get_xy_corr_fun(x,y)/max_e0*e0evol_vs_t(t))
        lt_factor  = correct_lifetime_(z, get_lt_corr_fun(x,y)*ltevol_vs_t(t))
        factor     = geo_factor*lt_factor
        return factor

    return total_correction_factor

def apply_all_correction(maps       : ASectorMap,
                         apply_temp : bool = True)->Callable:
    """
    Returns a function to get all correction factor for a
    given hit collection when (x,y,z,time) is provided,
    if an unique correction map is wanted to be used

    Parameters
    ----------
    maps : AsectorMap
        Selected correction map for doing geometric and lifetime correction
    apply_temp : Bool
        If True, time evolution will be taken into account

    Returns
    -------
        A function that returns complete time correction factor
    """

    return apply_all_correction_single_maps(maps, maps, maps, apply_temp)

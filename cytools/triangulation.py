# =============================================================================
# This file is part of CYTools.
#
# CYTools is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# CYTools is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# CYTools. If not, see <https://www.gnu.org/licenses/>.
# =============================================================================
#
# -----------------------------------------------------------------------------
# Description:  This module contains tools designed to compute triangulations.
# -----------------------------------------------------------------------------

# 'standard' imports
import ast
import copy
import itertools
import math
import re
import subprocess
import warnings

# 3rd party imports
import flint
import numpy as np
from numpy.typing import ArrayLike
from scipy.spatial import ConvexHull

# CYTools imports
from cytools import config
from cytools.cone import Cone
from cytools.toricvariety import ToricVariety
from cytools.utils import gcd_list, lll_reduce

class Triangulation:
    """
    This class handles triangulations of lattice polytopes. It can compute
    various properties of the triangulation, as well as construct a
    ToricVariety or CalabiYau object if the triangulation is suitable.

    :::important
    Generally, objects of this class should not be constructed directly by the
    end user. Instead, they should be created by various functions of the
    [`Polytope`](./polytope) class.
    :::

    ## Constructor

    ### `cytools.triangulation.Triangulation`

    **Description:**
    Constructs a `Triangulation` object describing a triangulation of a lattice
    polytope. This is handled by the hidden [`__init__`](#__init__) function.

    :::note
    If you construct a triangulation object directly by inputting a list of
    points they may be reordered to match the ordering of the points from the
    [`Polytope`](./polytope) class. This is to ensure that computations of
    toric varieties and Calabi-Yau manifolds are correct. To avoid this
    subtlety we discourage users from constructing Triangulation objects
    directly, and instead use the triangulation functions in the
    [`Polytope`](./polytope) class.
    :::

    **Arguments:**
    - `poly`: The ambient polytope of the points to be triangulated. If not
        specified, it's constructed as the convex hull of the given points.
    - `pts`: The list of points to be triangulated. Specified by labels.
    - `heights`: The heights specifying the regular triangulation. When not
        specified, construct based off of the backend:
            - (CGAL) Delaunay triangulation,
            - (QHULL) triangulation from random heights near Delaunay, or
            - (TOPCOM) placing triangulation.
        Heights can only be specified when using CGAL or QHull as the backend.
    - `make_star`: Whether to turn the triangulation into a star triangulation
        by deleting internal lines and connecting all points to the origin, or
        equivalently, by decreasing the height of the origin until it is much
        lower than all other heights.
    - `simplices`: Array-like of simplices specifying the triangulation. Each
        simplex is a list of point indices. This is useful when a triangulation
        was previously computed and it needs to be used again. Note that the
        ordering of the points needs to be consistent.
    - `check_input_simplices`: Whether to check if the input simplices define a
        valid triangulation.
    - `backend`: The backend used to compute the triangulation. Options are
        "qhull", "cgal", and "topcom". CGAL is the default as it is very
        fast and robust.
    - `verbosity`: The verbosity level.

    **Example:**
    We construct a triangulation of a polytope. Since this class is not
    intended to by initialized by the end user, we create it via the
    [`triangulate`](./polytope#triangulate) function of the
    [`Polytope`](./polytope) class. In this example the polytope is reflexive,
    so by default the triangulation is fine, regular, and star. Also, since the
    polytope is reflexive then by default only the lattice points not interior
    to facets are included in the triangulation.
    ```python {3}
    from cytools import Polytope
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
    t = p.triangulate()
    print(t)
    # A fine, regular, star triangulation of a 4-dimensional point
    # configuration with 7 points in ZZ^4
    ```
    """

    def __init__(self,
                 poly: "Polytope",
                 pts: ArrayLike,
                 heights: list = None,
                 make_star: bool = False,
                 simplices: ArrayLike = None,
                 check_input_simplices: bool = True,
                 check_heights: bool = True,
                 backend: str = "cgal",
                 verbosity: int = 1) -> None:
        """
        **Description:**
        Initializes a `Triangulation` object.

        **Arguments:**
        - `poly`: The ambient polytope of the points to be triangulated.
        - `pts`: The list of points to be triangulated. Specified by labels.
        - `heights`: The heights specifying the regular triangulation. When not
            specified, construct based off of the backend:
                - (CGAL) Delaunay triangulation,
                - (QHULL) triangulation from random heights near Delaunay, or
                - (TOPCOM) placing triangulation.
            Heights can only be specified when using CGAL or QHull as the
            backend.
        - `make_star`: Whether to turn the triangulation into a star
            triangulation by deleting internal lines and connecting all points
            to the origin, or equivalently, by decreasing the height of the
            origin until it is much lower than all other heights.
        - `simplices`: Array-like of simplices specifying the triangulation.
            Each simplex is a list of point indices. This is useful when a
            triangulation was previously computed and it needs to be used
            again. Note that the ordering of the points needs to be consistent.
        - `check_input_simplices`: Whether to check if the input simplices
            define a valid triangulation.
        - `check_heights`: Whether to check if the input/default heights define
            a valid/unique triangulation.
        - `backend`: The backend used to compute the triangulation. Options are
            "qhull", "cgal", and "topcom". CGAL is the default as it is very
            fast and robust.
        - `verbosity`: The verbosity level.

        **Returns:**
        Nothing.

        **Example:**
        This is the function that is called when creating a new
        `Triangulation` object. In this example the polytope is reflexive, so
        by default the triangulation is fine, regular, and star. Also, since
        the polytope is reflexive then by default only the lattice points not
        interior to facets are included in the triangulation.
        ```python {3}
        from cytools import Polytope
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        print(t)
        # A fine, regular, star triangulation of a 4-dimensional point
        # configuration with 7 points in ZZ^4
        ```
        """
        # initialize hidden attributes
        self.clear_cache()

        # Grab inputs
        # -----------
        # backend
        backend = backend.lower()
        if backend not in ['qhull', 'cgal', 'topcom', None]:
            raise ValueError(f"Invalid backend, {backend}. "+\
                             f"Options: {['qhull', 'cgal', 'topcom', None]}.")
        self._backend = backend

        # points (keep as temporary object for now)
        self._pt_labels = pts
        tmp_pts = np.array(poly.points(which=pts), dtype=int) # cast to int
        tmp_pts = {tuple(pt) for pt in tmp_pts}   # keep unique
        if len(tmp_pts) == 0:
            raise ValueError("Need at least 1 point.")
        
        # polytope
        self._poly = poly

        # simplices
        if simplices is not None:
            self._simplices = sorted([sorted(s) for s in simplices])
            self._simplices = np.asarray(self._simplices, dtype=int)
        else:
            self._simplices = None

        # Parse points
        # ------------
        # reorder to match Polytope class ordering
        # (the check `if pt in tmp_pts` is relevant if the
        #  triangulation is non-fine. Then there could be pt in poly_pts but
        #  not in tmp_pts)
        poly_pts = [tuple(pt) for pt in self._poly.points()]
        self._pts = [pt for pt in poly_pts if pt in tmp_pts]
        self._pts = np.asarray(self._pts)

        pts_tup = [tuple(pt) for pt in self._pts]

        # grab dimension info
        self._ambient_dim  = len( next(iter(tmp_pts)) )
        self._dim = np.linalg.matrix_rank([pt+(1,) for pt in tmp_pts])-1
        self._is_fulldim = (self._dim == self._ambient_dim)

        # if point config isn't full-dim, find better representation of points
        if self._is_fulldim:
            self._pts_optimal = self._pts
        else:
            self._pts_optimal = self._pts-self._pts[0]
            self._pts_optimal = lll_reduce(self._pts_optimal)
            self._pts_optimal = self._pts_optimal[:,-self._dim:]

        # find index of origin
        try:
            self._origin_index = pts_tup.index((0,)*self._poly.dim())
        except ValueError:
            # origin wasn't in pts_tup
            self._origin_index = -1
            make_star = False

        # map pt->triang_idx
        self._pts_dict = {pt:i for i, pt in enumerate(pts_tup)}

        # map triang_idx->poly_idx
        self._pts_triang_to_poly = {i:self._poly.points_to_indices(pt) for\
                                        i, pt in enumerate(self._pts)}

        # Save input triangulation, or construct it
        # -----------------------------------------
        heights = copy.deepcopy(heights)
        if self._simplices is not None:
            self._heights = None

            # check dimension
            if self._simplices.shape[1] != self._dim+1:
                simp_dim = self._simplices.shape[1]-1
                error_msg = f"Dimension of simplices, ({simp_dim}), " +\
                             "doesn't match polytope dimension (+1), "+\
                            f"{self._dim} (+1)..."
                raise ValueError(error_msg)

            if check_input_simplices:
                # only basic checks here. Most are in self.is_valid()
                # (do some checks here b/c otherwise self.is_valid() hits
                # errors)
                simp_inds = set(self._simplices.flatten())
                if min(simp_inds)<0:
                    error_msg = f"A simplex had index, {min(simp_inds)}, " +\
                                f"out of range [0,{len(self.points())-1}]"
                    raise ValueError(error_msg)
                elif max(simp_inds)>=len(self.points()):
                    error_msg = f"A simplex had index, {max(simp_inds)}, " +\
                                f"out of range [0,{len(self.points())-1}]"
                    raise ValueError(error_msg)

                # Check if the indices are in a sensible range
                # (i.e., [0,npts-1])
                # (this check is only sensical for fine triangulations)
                #if set(self._simplices.flatten()) != {*range(len(self.points()))}:
                #    simp_inds = sorted(set(self._simplices.flatten()))
                #    npts = len(self.points())
                #    error_msg = f"Indices in simplices, {simp_inds}, " +\
                #                f"don't span range(len(self.points())={npts})..."
                #    raise ValueError(error_msg)

            # convert simplices to star
            if make_star:
                _to_star(self)

            # ensure simplices define valid triangulation
            if check_input_simplices and not self.is_valid():
                raise ValueError("Simplices don't form valid triangulation.")
        else:
            # self._simplices==None... construct simplices from heights

            self._is_regular = (None if (backend == "qhull") else True)
            self._is_valid = True

            default_triang = heights is None
            if default_triang:
                # construct the heights
                if backend is None:
                    raise ValueError("Simplices must be specified when working"
                                     "without a backend")

                # Heights need to be perturbed around the Delaunay heights for
                # QHull or the triangulation might not be regular. If using
                # CGAL then they are not perturbed.
                if backend == "qhull":
                    heights = [np.dot(p,p) + np.random.normal(0,0.05)\
                                                    for p in self._pts]
                elif backend == "cgal":
                    heights = [np.dot(p,p) for p in self._pts]
                else: # TOPCOM
                    heights = None
            else:
                # check the heights
                if len(heights) != len(pts):
                    raise ValueError("Need same number of heights as points.")

            if heights is None:
                self._heights = None
            else:
                self._heights = np.asarray(heights)

            # Now run the appropriate triangulation function
            if backend == "qhull":
                self._simplices = _qhull_triangulate(self._pts_optimal,\
                                                     self._heights)

                # convert to star
                if make_star:
                    _to_star(self)

            elif backend == "cgal":
                self._simplices = _cgal_triangulate(self._pts_optimal,\
                                                    self._heights)
                
                # can obtain star more quickly than in QHull by setting height
                # of origin to be much lower than others
                # (can't do this in QHull since it sometimes causes errors...)
                if make_star:
                    assert self._origin_index == 0

                    origin_step = max(100, (max(self._heights[1:]) -\
                                                    min(self._heights[1:])))
                    
                    while self._simplices[:,0].any():
                        self._heights[0] -= origin_step
                        self._simplices = _cgal_triangulate(self._pts_optimal,\
                                                            self._heights)
            else: # Use TOPCOM
                self._simplices = _topcom_triangulate(self._pts_optimal)

                # convert to star
                if make_star:
                    _to_star(self)

            # check that the heights uniquely define this triangulation
            if check_heights and (self._heights is not None):
                self.check_heights(verbosity-default_triang)

        # Make sure that the simplices are sorted
        self._simplices = sorted([sorted(s) for s in self._simplices])
        self._simplices = np.array(self._simplices)

    # defaults
    # ========
    def __repr__(self) -> str:
        """
        **Description:**
        Returns a string describing the triangulation.

        **Arguments:**
        None.

        **Returns:**
        A string describing the triangulation.

        **Example:**
        This function can be used to convert the triangulation to a string or
        to print information about the triangulation.
        ```python {3,4}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        poly_info = str(t) # Converts to string
        print(t) # Prints triangulation info
        # A fine, regular, star triangulation of a 4-dimensional point configuration with 7 points in ZZ^4
        ```
        """
        fine_str = "fine" if self.is_fine() else "non-fine"

        regular_str = ""
        if self._is_regular is not None:
            regular_str = ", "
            regular_str += "regular" if self._is_regular else "irregular"

        star_str = ""
        if self.polytope().is_reflexive():
            star_str = ", "
            star_str += "star" if self.is_star() else "non-star"

        return (f"A " + fine_str + regular_str + star_str +\
                f" triangulation of a {self.dim()}-dimensional " +\
                f"point configuration with {len(self._pts)} points " +\
                f"in ZZ^{self.ambient_dim()}")

    def __eq__(self, other: "Triangulation") -> bool:
        """
        **Description:**
        Implements comparison of triangulations with ==.

        **Arguments:**
        - `other`: The other triangulation that is being compared.

        **Returns:**
        The truth value of the triangulations being equal.

        **Example:**
        We construct two triangulations and compare them.
        ```python {4}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t1 = p.triangulate(backend="qhull")
        t2 = p.triangulate(backend="topcom")
        t1 == t2
        # True
        ```
        """
        # check if other is even a triangulation
        if not isinstance(other, Triangulation):
            return False

        # check that we have the same polytope and simplices
        our_simps = sorted(self.simplices().tolist())
        other_simps = sorted(other.simplices().tolist())

        return (self.polytope() == other.polytope() and
                                                    our_simps == other_simps)

    def __ne__(self, other: "Triangulation") -> bool:
        """
        **Description:**
        Implements comparison of triangulations with !=.

        **Arguments:**
        - `other`: The other triangulation that is being compared.

        **Returns:**
        The truth value of the triangulations being different.

        **Example:**
        We construct two triangulations and compare them.
        ```python {4}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t1 = p.triangulate(backend="qhull")
        t2 = p.triangulate(backend="topcom")
        t1 != t2
        # False
        ```
        """
        return(not self.__eq__(other))

    def __hash__(self) -> int:
        """
        **Description:**
        Implements the ability to obtain hash values from triangulations.

        **Arguments:**
        None.

        **Returns:**
        The hash value of the triangulation.

        **Example:**
        We compute the hash value of a triangulation. Also, we construct a set
        and a dictionary with a triangulation, which make use of the hash
        function.
        ```python {3,4,5}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        h = hash(t) # Obtain hash value
        d = {t: 1} # Create dictionary with triangulation keys
        s = {t} # Create a set of triangulations
        ```
        """
        if self._hash is None:
            pt_hash = hash(tuple(sorted(tuple(v) for v in self.points())))
            simps = tuple(sorted(tuple(sorted(s)) for s in self.simplices()))
            self._hash = hash((pt_hash,) + simps)

        return self._hash

    # caching
    # =======
    def _dump(self) -> dict:
        """
        **Description:**
        Get every class variable.

        No copying is done, so be careful with mutability!

        **Arguments:**
        None.

        **Returns:**
        Dictionary mapping variable name to value.
        """
        return self.__dict__

    def clear_cache(self, recursive: bool = False) -> None:
        """
        **Description:**
        Clears the cached results of any previous computation.

        **Arguments:**
        - `recursive`: Whether to also clear the cache of the ambient polytope.

        **Returns:**
        Nothing.

        **Example:**
        We construct a triangulation, compute its GKZ vector, clear the cache
        and then compute it again.
        ```python {4}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        gkz_phi = t.gkz_phi() # Computes the GKZ vector
        t.clear_cache()
        gkz_phi = t.gkz_phi() # The GKZ vector is recomputed
        ```
        """
        self._automorphism_orbit = dict()
        self._gkz_phi = None
        self._hash = None
        self._is_fine = None
        self._is_regular = None
        self._is_star = None
        self._is_valid = None
        self._secondary_cone = [None]*2
        self._sr_ideal = None
        self._toricvariety = None

        self._restricted_simplices = dict()

        if recursive:
            self._poly.clear_cache()

    # getters
    # =======
    def polytope(self) -> "Polytope":
        """
        **Description:**
        Returns the polytope being triangulated.

        **Arguments:**
        None.

        **Returns:**
        The ambient polytope.

        **Example:**
        We construct a triangulation and check that the polytope that this
        function returns is the same as the one we used to construct it.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.polytope() is p
        # True
        ```
        """
        return self._poly

    def points(self) -> np.ndarray:
        """
        **Description:**
        Returns the points of the triangulation. Note that these are not
        necessarily equal to the lattice points of the polytope they define.

        **Arguments:**
        None.

        **Returns:**
        The points of the triangulation.

        **Aliases:**
        `pts`.

        **Example:**
        We construct a triangulation and print the points in the point
        configuration. Note that since the polytope is reflexive, then by
        default only the lattice points not interior to facets were used.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.points()
        # array([[ 0,  0,  0,  0],
        #        [-1, -1, -6, -9],
        #        [ 0,  0,  0,  1],
        #        [ 0,  0,  1,  0],
        #        [ 0,  1,  0,  0],
        #        [ 1,  0,  0,  0],
        #        [ 0,  0, -2, -3]])
        ```
        """
        return np.array(self._pts)
    # aliases
    pts = points

    def dimension(self) -> int:
        """
        **Description:**
        Returns the dimension of the triangulated point configuration.

        **Arguments:**
        None.

        **Returns:**
        The dimension of the triangulation.

        **Aliases:**
        `dim`.

        **Example:**
        We construct a triangulation and find its dimension.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.dimension()
        # 4
        ```
        """
        return self._dim
    # aliases
    dim = dimension

    def ambient_dimension(self) -> int:
        """
        **Description:**
        Returns the dimension of the ambient lattice.

        **Arguments:**
        None.

        **Returns:**
        The dimension of the ambient lattice.

        **Aliases:**
        `ambient_dim`.

        **Example:**
        We construct a triangulation and find its ambient dimension.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.ambient_dim()
        # 4
        ```
        """
        return self._poly._dim_ambient
    # aliases
    ambient_dim = ambient_dimension

    def is_fine(self) -> bool:
        """
        **Description:**
        Returns True if the triangulation is fine (all the points are used), and
        False otherwise. Note that this only checks if it is fine with respect
        to the point configuration, not with respect to the full set of lattice
        points of the polytope.

        **Arguments:**
        None.

        **Returns:**
        The truth value of the triangulation being fine.

        **Example:**
        We construct a triangulation and check if it is fine.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.is_fine()
        # True
        ```
        """
        # check if we know the answer
        if self._is_fine is not None:
            return self._is_fine

        # calculate the answer
        N_used_pts = len(set.union(*[set(s) for s in self._simplices]))
        self._is_fine = (N_used_pts == len(self._pts))

        # return
        return self._is_fine

    def is_star(self, star_origin = None) -> bool:
        """
        **Description:**
        Returns True if the triangulation is star and False otherwise. The star
        origin is assumed to be the origin, so for polytopes that don't contain
        the origin this function will always return False unless `star_origin`
        is specified.

        **Arguments:**
        - `star_origin`: The index of the origin of the star triangulation

        **Returns:**
        The truth value of the triangulation being star.

        **Example:**
        We construct a triangulation and check if it is star.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.is_star()
        # True
        ```
        """
        # check if we know the answer
        if star_origin is not None:
            return all(star_origin in s for s in self._simplices)

        # calculate the answer
        if self._is_star is None:
            try:
                star_origin = self.points_to_indices([0]*self.dim())
                self._is_star = all(star_origin in s for s in self._simplices)
            except:
                self._is_star = False

        # return
        return self._is_star

    def get_toric_variety(self) -> ToricVariety:
        """
        **Description:**
        Returns a ToricVariety object corresponding to the fan defined by the
        triangulation.

        **Arguments:**
        None.

        **Returns:**
        The toric variety arising from the triangulation.

        **Example:**
        We construct a triangulation and obtain the resulting toric variety.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.get_toric_variety()
        # A simplicial compact 4-dimensional toric variety with 9 affine patches
        ```
        """
        # check if we know the answer
        if self._toricvariety is not None:
            return self._toricvariety

        # check if the question makes sense
        if not self._is_fulldim:
            raise NotImplementedError("Toric varieties can only be " +\
                        "constructed from full-dimensional triangulations.")
        if not self.is_star():
            raise NotImplementedError("Toric varieties can only be " +\
                        "constructed from star triangulations.")

        # initialize the answer
        self._toricvariety = ToricVariety(self)

        # return
        return self._toricvariety

    def get_cy(self, nef_partition: list[tuple[int]] = None) -> "CalabiYau":
        """
        **Description:**
        Returns a CalabiYau object corresponding to the anti-canonical
        hypersurface on the toric variety defined by the fine, star, regular
        triangulation. If a nef-partition is specified then it returns the
        complete intersection Calabi-Yau that it specifies.

        :::note
        Only Calabi-Yau 3-fold hypersurfaces are fully supported. Other
        dimensions and CICYs require enabling the experimental features of
        CYTools. See [experimental features](./experimental) for more details.
        :::

        **Arguments:**
        - `nef_partition`: A list of tuples of indices specifying a
            nef-partition of the polytope, which correspondingly defines a
            complete intersection Calabi-Yau.

        **Returns:**
        The Calabi-Yau arising from the triangulation.

        **Example:**
        We construct a triangulation and obtain the Calabi-Yau hypersurface in
        the resulting toric variety.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.get_cy()
        # A Calabi-Yau 3-fold hypersurface with h11=2 and h21=272 in a 4-dimensional toric variety
        ```
        """
        return self.get_toric_variety().get_cy(nef_partition)

    # aliases
    compute_cy = get_cy
    cy = get_cy

    # points
    # ======
    def points_to_indices(self, points: ArrayLike) -> "np.ndarray | int":
        """
        **Description:**
        Returns the list of indices corresponding to the given points. It also
        accepts a single point, in which case it returns the corresponding
        index. Note that these indices are not necessarily equal to the
        corresponding indices in the polytope.

        **Arguments:**
        - `points`: A point or a list of points.

        **Returns:**
        The list of indices corresponding to the given points, or the index of
        the point if only one is given.

        **Example:**
        We construct a triangulation and find the indices of some of its points.
        ```python {3,5}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.points_to_indices([-1,-1,-6,-9]) # We input a single point, so a single index is returned
        # 1
        t.points_to_indices([[-1,-1,-6,-9],[0,0,0,0],[0,0,1,0]]) # We input a list of points, so a list of indices is returned
        # array([1, 0, 3])
        ```
        """
        if len(np.array(points).shape) == 1:
            if np.array(points).shape[0] == 0:
                # 0 points
                return np.zeros(0, dtype=int)
            else:
                # 1 point
                return self._pts_dict[tuple(points)]

        # >1 points
        return np.array([self._pts_dict[tuple(pt)] for pt in points])

    def points_to_poly_indices(self, points: ArrayLike)->"np.ndarray|int":
        """
        **Description:**
        Takes a list of indices of points of the triangulation and it returns
        the corresponding indices of the polytope. It also accepts a single
        entry, in which case it returns the corresponding index.

        **Arguments:**
        - `points`: A list of indices of points.

        **Returns:**
        The list of indices corresponding to the given points. Or the index of
        the point if only one is given.

        **Example:**
        We construct a triangulation and convert from indices of the
        triangulation to indices of the polytope. Since the indices of the two
        classes usually match, we will construct a triangulation that does not
        include the origin, so that indices will be shifted by one.
        ```python {7,9}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate(points=[1,2,3,4,5,6,7,8,9]) # We exclude point 0, which is the origin
        t.points_to_indices([-1,-1,-6,-9]) # We get the index of a point in the triangulation
        # 0
        p.points_to_indices([-1,-1,-6,-9]) # The same point corresponds to a different index in the polytope
        # 1
        t.triangulation_to_polytope_indices(0) # We can convert an index with this function
        # 1
        t.triangulation_to_polytope_indices([0,1,2,3,4,5,6,7,8]) # And we can convert multiple indices in the same way
        # array([1, 2, 3, 4, 5, 6, 7, 8, 9])
        ```
        """
        if len(np.array(points).shape) == 0:
            # <= 1 point
            return self._pts_triang_to_poly[points]

        # >1 points
        return np.array([self._pts_triang_to_poly[pt] for pt in points])
    # aliases
    triangulation_to_polytope_indices = points_to_poly_indices

    # triangulation
    # =============
    # sanity checks
    # -------------
    def is_valid(self, backend: str = None) -> bool:
        """
        **Description:**
        Returns True if the presumed triangulation meets all requirements to be
        a triangulation. The simplices must cover the full volume of the convex
        hull, and they cannot intersect at full-dimensional regions.

        **Arguments:**
        - `backend`: The optimizer used for the computation. The available
            options are the backends of the [`is_solid`](./cone#is_solid)
            function of the [`Cone`](./cone) class. If not specified, it will
            be picked automatically.

        **Returns:**
        The truth value of the triangulation being valid.

        **Example:**
        This function is useful when constructing a triangulation from a given
        set of simplices. We show this in this example.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate(simplices=[[0,1,2,3,4],[0,1,2,3,5],[0,1,2,4,5],[0,1,3,4,5],[0,2,3,4,5]]) # It is already used here unless using check_input_simplices=False
        t.is_valid()
        # True
        ```
        """
        # check if we know the answer
        if self._is_valid is not None:
            return self._is_valid

        # calculate the answer
        simps = self.simplices()
        
        if simps.shape[0] == 1:
            # triangulation is trivial
            self._is_valid = True
            return self._is_valid

        # If the triangulation is presumably regular, then we can check if
        # heights inside the secondary cone yield the same triangulation.
        if self.is_regular(backend=backend):
            tmp_triang = Triangulation(self.polytope(), self._pt_labels,\
                                       heights=self.heights(), make_star=False)

            simps1 = sorted(sorted(s) for s in self.simplices().tolist())
            simps2 = sorted(sorted(s) for s in tmp_triang.simplices().tolist())

            self._is_valid = (simps1==simps2)
            return self._is_valid

        # If it is not regular, then we check this using the definition of a
        # triangulation. This can be quite slow for large polytopes.

        # append a 1 to each point
        pts = self._pts_optimal
        pts_ext = [list(pt)+[1,] for pt in pts]

        # We first check if the volumes add up to the volume of the polytope
        v = 0
        for s in simps:
            tmp_v = abs(int(round(np.linalg.det([pts_ext[i] for i in s]))))

            if tmp_v == 0:
                self._is_valid = False
                return self._is_valid

            v += tmp_v

        poly_vol = int(round(ConvexHull(pts).volume*math.factorial(self._dim)))
        if v != poly_vol:
            self._is_valid = False
            return self._is_valid

        # Finally, check if simplices have full-dimensional intersections
        for i,s1 in enumerate(simps):
            for s2 in simps[i+1:]:
                inters = Cone(pts_ext[s1]).intersection(Cone(pts_ext[s2]))

                if inters.is_solid():
                    self._is_valid = False
                    return self._is_valid

        # return
        self._is_valid = True
        return self._is_valid

    def check_heights(self, verbosity: int = 1) -> bool:
        """
        **Description:**
        Check if the heights uniquely define a triangulation. That is, if they
        do not lie on a wall of the generated secondary cone.

        If heights don't uniquely correspond to a trinagulation, delete the
        heights so they are re-calculated (keep triangulation, though...)

        **Arguments:**
        - `verbosity`: The verbosity level.

        **Returns:**
        Nothing.
        """
        # find hyperplanes that we are within eps of wall
        eps = 1e-6
        hyp_dist = np.matmul(self.secondary_cone().hyperplanes(),\
                             self._heights)
        not_interior = hyp_dist<eps

        # if we are close to any walls
        if not_interior.any():
            self._heights = None

            if verbosity>1:
                print(f"Triangulation: height-vector is within {eps}"+\
                       " of a wall of the secondary cone... heights "+\
                       "likely don't define a unique triangulation " +\
                       "(common for Delaunay)...")
                print("Will recalculate more appropriate heights " +\
                      "for the (semi-arbitrarily chosen) " +\
                      "triangulation...")

    # main method
    # -----------
    def simplices(self,
                  on_faces_dim: int = None,
                  on_faces_codim: int = None,
                  split_by_face: bool = False,
                  as_np_array: bool = True) -> "set | np.ndarray":
        """
        **Description:**
        Returns the simplices of the triangulation. It also has the option of
        restricting the simplices to faces of the polytope of a particular
        dimension or codimension. This restriction is useful for checking CY
        equivalences from different triangulations.

        **Arguments:**
        - `on_faces_dim: Restrict the simplices to faces of the polytope of a
            given dimension.
        - `on_faces_codim`: Restrict the simplices to faces of the polytope of
            a given codimension.

        **Returns:**
        The simplices of the triangulation.

        **Example:**
        We construct a triangulation and find its simplices. We also find the
        simplices the lie on 2-faces of the polytope.
        ```python {3,9}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.simplices()
        # array([[0, 1, 2, 3, 4],
        #        [0, 1, 2, 3, 5],
        #        [0, 1, 2, 4, 5],
        #        [0, 1, 3, 4, 5],
        #        [0, 2, 3, 4, 5]])
        t.simplices(on_faces_dim=2)
        # [[1 2 3]
        #  [1 2 4]
        #  [1 2 5]
        #  [1 3 4]
        #  [1 3 5]
        #  [1 4 5]
        #  [2 3 4]
        #  [2 3 5]
        #  [2 4 5]
        #  [3 4 5]]
        ```
        """
        # input parsing
        if (on_faces_dim is None) and (on_faces_codim is None):
            if as_np_array:
                return np.array(self._simplices)
            else:
                return set(frozenset(simp) for simp in self._simplices)
        elif on_faces_dim is not None:
            faces_dim = on_faces_dim
        else:
            faces_dim = self.dim()-on_faces_codim

        if faces_dim<0 or faces_dim>self.dim():
            raise ValueError("Invalid face dimension.")

        # restrict simplices to faces
        if faces_dim not in self._restricted_simplices:
            full_simp = [frozenset(s) for s in self._simplices]

            # get face information
            faces = self.polytope().faces(faces_dim)

            faces_pts = [[pt for pt in face.points()\
                            if tuple(pt) in self._pts_dict] for face in faces]
            faces_inds = [frozenset(self.points_to_indices(pts)) for pts\
                                                                in faces_pts]

            # actually restrict            
            restricted = []
            for f in faces_inds:
                restricted.append(set())
                for s in full_simp:
                    inters = f & s
                    if len(inters) == faces_dim+1:
                        restricted[-1].add(inters)

            self._restricted_simplices[faces_dim] = restricted

        # return
        if split_by_face:
            out = self._restricted_simplices[faces_dim]
            if as_np_array:
                out = [np.array(sorted(sorted(s) for s in face)) for face in out]
        else:
            out = set().union(*self._restricted_simplices[faces_dim])
            if as_np_array:
                return np.array(sorted(sorted(s) for s in out))
        
        return out
    # aliases
    simps = simplices

    # regularity
    # ----------
    def secondary_cone(self,
                       backend: str = None,
                       include_points_not_in_triangulation: bool = True) -> Cone:
        """
        **Description:**
        Computes the secondary cone of the triangulation (also called the cone
        of strictly convex piecewise linear functions). It is computed by
        finding the defining hyperplane equations. The triangulation is regular
        if and only if this cone is solid (i.e. full-dimensional), in which
        case the points in the interior correspond to heights that give rise to
        the triangulation.

        **Arguments:**
        - `backend` *(str, optional)*: Specifies how the cone is computed.
            Options are "native", which uses a native implementation of an
            algorithm by Berglund, Katz and Klemm, or "topcom" which uses
            differences of GKZ vectors for the computation.
        - `include_points_not_in_triangulation`: This flag allows the exclusion
            of points that are not part of the triangulation. This can be done
            to check regularity faster, but this cannot be used if the actual
            cone in the secondary fan is needed.

        **Returns:**
        *(Cone)* The secondary cone.

        **Aliases:**
        `cpl_cone`.

        **Example:**
        We construct a triangulation and find its secondary cone.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.secondary_cone()
        # A rational polyhedral cone in RR^7 defined by 3 hyperplanes normals
        ```
        """
        # set the backend
        backends = (None, "native", "topcom")
        if backend not in backends:
            raise ValueError(f"Options for backend are: {backends}")

        if backend is None:
            if self.is_fine() or (not include_points_not_in_triangulation):
                backend = "native"
            else:
                backend = "topcom"

        if (backend == "native" and (not self.is_fine()) and\
                                        include_points_not_in_triangulation):
            warnings.warn("Native backend is not supported when including "
                          "points that are not in the triangulation. Using "
                          "TOPCOM...")
            backend = "topcom"

        # calculate the secondary cone
        args_id = int(include_points_not_in_triangulation)

        if self._secondary_cone[args_id] is not None:
            return self._secondary_cone[args_id]

        if backend == "native":
            pts_ext = [list(pt)+[1,] for pt in self._pts_optimal]

            m = np.zeros((self.dim()+1, self.dim()+2), dtype=int)
            full_v = np.zeros(len(pts_ext), dtype=int)

            if self.is_star():
                # star triangulations all share 0th point, the origin
                star_origin = self.points_to_indices([0]*self.dim())
                simps = [set(s)-{star_origin} for s in self._simplices]
                dim = self.dim()-1
                m[:,-1] = pts_ext[star_origin]
            else:
                simps = [set(s) for s in self._simplices]
                dim = self.dim()

            null_vecs = set()
            for i,s1 in enumerate(simps):
                for s2 in simps[i+1:]:
                    # ensure that the simps have a large enough intersection
                    comm_pts = s1 & s2
                    if len(comm_pts) != dim:
                        continue

                    diff_pts = list(s1 ^ s2)
                    comm_pts = list(comm_pts)
                    for j,pt in enumerate(diff_pts):    m[:,j] = pts_ext[pt]
                    for j,pt in enumerate(comm_pts):    m[:,j+2] = pts_ext[pt]

                    # calculate nullspace/hyperplane ineq
                    v = flint.fmpz_mat(m.tolist()).nullspace()[0]
                    v = np.array(v.transpose().tolist()[0], dtype=int)

                    # ensure the sign is correct
                    if v[0] < 0:
                        v *= -1

                    # Reduce the vector
                    g = gcd_list(v)
                    if g != 1:
                        v //= g

                    # Construct the full vector (including all points)
                    # (could get some more performance by allowing sparse vectors as Cone argument...)
                    for i,pt in enumerate(diff_pts):    full_v[pt] = v[i]
                    for i,pt in enumerate(comm_pts):    full_v[pt] = v[i+2]
                    if self.is_star():
                        full_v[star_origin] = v[-1]

                    null_vecs.add(tuple(full_v))
                    
                    for i,pt in enumerate(diff_pts):    full_v[pt] = 0
                    for i,pt in enumerate(comm_pts):    full_v[pt] = 0
                    if self.is_star():
                        full_v[star_origin] = v[-1]

            # define the secondary cone
            null_vecs = list(null_vecs)

            if len(null_vecs):
                hyps = null_vecs
            else:
                hyps = np.zeros((0,len(pts_ext)), dtype=int)

            self._secondary_cone[args_id] = Cone(hyperplanes=hyps,\
                                                 check=False)

            # return
            return self._secondary_cone[args_id]

        # Otherwise we compute this cone by using differences of GKZ vectors.
        gkz_phi = self.gkz_phi()
        diffs = []
        for t in self.neighbor_triangulations(only_fine=False,\
                                              only_regular=False,\
                                              only_star=False):
            diffs.append(t.gkz_phi()-gkz_phi)

        self._secondary_cone[args_id] = Cone(hyperplanes=diffs)

        return self._secondary_cone[args_id]
    # aliases
    cpl_cone = secondary_cone

    def is_regular(self, backend: str = None) -> bool:
        """
        **Description:**
        Returns True if the triangulation is regular and False otherwise.

        **Arguments:**
        - `backend`: The optimizer used for the computation. The available
            options are the backends of the [`is_solid`](./cone#is_solid)
            function of the [`Cone`](./cone) class. If not specified, it will
            be picked automatically.

        **Returns:**
        The truth value of the triangulation being regular.

        **Example:**
        We construct a triangulation and check if it is regular.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.is_regular()
        # True
        ```
        """
        # check if we know the answer
        if self._is_regular is not None:
            return self._is_regular

        # calculate the answer
        if self.simplices().shape[0] == 1:
            self._is_regular = True
        else:
            C = self.secondary_cone(include_points_not_in_triangulation=False)
            self._is_regular = C.is_solid(backend=backend)

        # return
        return self._is_regular

    def heights(self,
                integral: bool = False,
                backend: str = None) -> np.ndarray:
        """
        **Description:**
        Returns the a height vector if the triangulation is regular. An
        exception is raised if a height vector could not be found either
        because the optimizer failed or because the triangulation is not
        regular.

        **Arguments:**
        - `integral`: Whether to find an integral height vector.
        - `backend`: The optimizer used for the computation. The available
            options are the backends of the
            [`find_interior_point`](./cone#find_interior_point) function of the
            [`Cone`](./cone) class. If not specified, it will be picked
            automatically.

        **Returns:**
        A height vector giving rise to the triangulation.

        **Example:**
        We construct a triangulation and find a height vector that generates it.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]])
        t = p.triangulate()
        t.heights()
        # array([0., 0., 0., 0., 0., 1.])
        ```
        """
        # check if we already know the heights...
        if self._heights is not None:
            heights_out = self._heights.copy()

            # convert to integral heights, if desired
            if integral and (heights_out.dtype==float):
                warnings.warn("Potential rounding errors... better to" +\
                                            "solve LP problem in this case...")
                heights_out = np.rint(heights_out/gcd_list(heights_out))

            return heights_out.astype(int if integral else float)

        # need to calculate the heights
        Npts = self._pts.shape[0]
        if (self._simplices.shape[0]==1) and (self._simplices.shape[1]==Npts):
            # If the triangulation is trivial we just return a vector of zeros
            self._heights = np.zeros(Npts, dtype=(int if integral else float))
        else:
            # Otherwise we find a point in the secondary cone
            C = self.secondary_cone(include_points_not_in_triangulation=True)
            self._heights = C.find_interior_point(integral=integral,
                                                  backend=backend)

        return self._heights.copy()

    # symmetries
    # ==========
    def automorphism_orbit(self,
                           automorphism: "int | ArrayLike" = None,
                           on_faces_dim: int = None,
                           on_faces_codim: int = None) -> np.ndarray:
        """
        **Description:**
        Returns all of the triangulations of the polytope that can be obtained
        by applying one or more polytope automorphisms to the triangulation.

        It also has the option of restricting the simplices to faces of the
        polytope of a particular dimension or codimension. This restriction is
        useful for checking CY equivalences from different triangulations.

        :::note
        Depending on how the point configuration was constructed, it may be the
        case that the automorphism group of the point configuration is larger
        or smaller than the one from the polytope. This function only uses the
        subset of automorphisms of the polytope that are also automorphisms of
        the point configuration.
        :::

        **Arguments:**
        - `automorphism`: The index or list of indices of the polytope
            automorphisms to use. If not specified it uses all automorphisms.
        - `on_faces_dim`: Restrict the simplices to faces of the polytope of a
            given dimension.
        - `on_faces_codim`: Restrict the simplices to faces of the polytope of
            a given codimension.

        **Returns:**
        The list of triangulations obtained by performing automorphisms
        transformations.

        **Example:**
        We construct a triangulation and find some of its automorphism orbits.
        ```python {3,9}
        p = Polytope([[-1,0,0,0],[-1,1,0,0],[-1,0,1,0],[2,-1,0,-1],[2,0,-1,-1],[2,-1,-1,-1],[-1,0,0,1],[-1,1,0,1],[-1,0,1,1]])
        t = p.triangulate()
        orbit_all_autos = t.automorphism_orbit()
        print(len(orbit_all_autos))
        # 36
        orbit_all_autos_2faces = t.automorphism_orbit(on_faces_dim=2)
        print(len(orbit_all_autos_2faces))
        # 36
        orbit_sixth_auto = t.automorphism_orbit(automorphism=5)
        print(len(orbit_sixth_auto))
        # 2
        orbit_list_autos = t.automorphism_orbit(automorphism=[5,6,9])
        print(len(orbit_list_autos))
        # 12
        ```
        """
        # sanity checks
        if not self._is_fulldim:
            raise NotImplementedError("Automorphisms can only be computed " +\
                                "for full-dimensional point configurations.")

        # input parsing
        if (on_faces_dim is None) and (on_faces_codim is None):
            faces_dim = self.dim()
        elif on_faces_dim is not None:
            faces_dim = on_faces_dim
        else:
            faces_dim = self.dim()-on_faces_codim

        if automorphism is None:
            orbit_id = (None, faces_dim)
        else:
            try:    orbit_id = (tuple(automorphism), faces_dim)
            except: orbit_id = ((automorphism,), faces_dim)

        # return answer if known
        if orbit_id in self._automorphism_orbit:
            return np.array(self._automorphism_orbit[orbit_id])

        # calculate orbit
        simps = self.simplices(on_faces_dim=faces_dim)
        autos = self.polytope().automorphisms(as_dictionary=True)

        # collect automorphisms of polytope that are also automorphisms of
        # the triangulation point configuration
        pts = [tuple(pt) for pt in self.polytope().points()]
        good_autos = []
        for i in range(len(autos)):
            for j,k in autos[i].items():
                # user-input 'allowed' automorphims
                if (orbit_id[0] is not None) and (i>0)\
                                             and (i not in orbit_id[0]):
                    # non-trivial automorphism that isn't specifically allowed
                    break

                # check if pts[j] and pts[k] are either both in the
                # triangulation, or both not in it
                if (pts[j] in self._pts_dict) != (pts[k] in self._pts_dict):
                    # oops! One pt is in the triangulation while other isn't!
                    break
            else:
                good_autos.append(i)

        # Finally, we
        #   1) reindex the 'good' automorphisms so that the indices match the
        #      indices of the point configuration and
        #   2) remove the bad automorphisms to make sure they are not used (we
        #      just replace them with None
        for i in range(len(autos)):
            # check if it is a 'bad' automorphism
            if i not in good_autos:
                autos[i] = None
                continue

            # it's a 'good' automorphism
            temp = {}
            for j,jj in autos[i].items():
                if (pts[j] in self._pts_dict) and (pts[jj] in self._pts_dict):
                    temp[self._pts_dict[pts[j]]] = self._pts_dict[pts[jj]]
            autos[i] = temp

        # define helper function
        apply_auto = lambda auto: tuple(sorted(\
                    tuple(sorted( [auto[i] for i in s] )) for s in simps ))

        # apply the automorphisms
        orbit = set()
        for j,a in enumerate(autos):
            # skip if it is a 'bad' automorphism
            if a is None:   continue

            # it's a 'good' automorphism
            orbit.add(apply_auto(a))

        if automorphism is not None:
            # keep applying autos until we stop getting new triangulations
            while True:
                new_triangs = []

                for simps in orbit:
                    for i in orbit_id[0]:
                        new_triang = apply_auto(autos[i])

                        if new_triang not in orbit:
                            new_triangs.append(new_triang)

                if len(new_triangs):
                    for t in new_triangs:
                        orbit.add(t)
                else:
                    break

        self._automorphism_orbit[orbit_id] = np.array(sorted(orbit))
        return np.array(self._automorphism_orbit[orbit_id])

    def is_equivalent(self,
                      other: "Triangulation",
                      use_automorphisms: bool = True,
                      on_faces_dim: int = None,
                      on_faces_codim: int = None) -> bool:
        """
        **Description:**
        Compares two triangulations with or without allowing automorphism
        transformations and with the option of restricting to faces of a
        particular dimension.

        **Arguments:**
        - `other`: The other triangulation that is being compared.
        - `use_automorphisms`: Whether to check the equivalence using
            automorphism transformations. This flag is ignored for point
            configurations that are not full dimensional.
        - `on_faces_dim`: Restrict the simplices to faces of the polytope of a
            given dimension.
        - `on_faces_codim`: Restrict the simplices to faces of the polytope of
            a given codimension.

        **Returns:**
        The truth value of the triangulations being equivalent under the
        specified parameters.

        **Example:**
        We construct two triangulations and check whether they are equivalent
        under various conditions.
        ```python {5,7,9}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[-1,1,1,0],[0,-1,-1,0],[0,0,0,1],[1,-2,1,1],[-2,2,1,-1],[1,1,-1,-1]])
        triangs_gen = p.all_triangulations()
        t1 = next(triangs_gen)
        t2 = next(triangs_gen)
        t1.is_equivalent(t2)
        # False
        t1.is_equivalent(t2, on_faces_dim=2)
        # True
        t1.is_equivalent(t2, on_faces_dim=2, use_automorphisms=False)
        # True
        ```
        """
        if self.polytope() != other.polytope():
            return False

        # check via automorphisms
        if self._is_fulldim and use_automorphisms:
            orbit1 = self.automorphism_orbit(on_faces_dim=on_faces_dim,\
                                             on_faces_codim=on_faces_codim)
            orbit2 = other.automorphism_orbit(on_faces_dim=on_faces_dim,\
                                              on_faces_codim=on_faces_codim)

            return (orbit1.shape==orbit2.shape) and all((orbit1==orbit2).flat)

        # check via simplices
        simp1 = self.simplices(on_faces_dim=on_faces_dim,\
                               on_faces_codim=on_faces_codim)
        simp2 = other.simplices(on_faces_dim=on_faces_dim,\
                                on_faces_codim=on_faces_codim)

        return (simp1.shape==simp2.shape) and all((simp1==simp2).flat)

    # flips
    # =====
    def neighbor_triangulations(self,
                                only_fine: bool = False,
                                only_regular: bool = False,
                                only_star: bool = False,
                                backend: str = None,
                                verbose : bool = False)->list["Triangulation"]:
        """
        **Description:**
        Returns the list of triangulations that differ by one bistellar flip
        from the current triangulation. The computation is performed with a
        modified version of TOPCOM. There is the option of limiting the flips
        to fine, regular, and star triangulations. An additional backend is
        used to check regularity, as checking this with TOPCOM is very slow for
        large polytopes.

        **Arguments:**
        - `only_fine`: Restricts to fine triangulations.
        - `only_regular`: Restricts the to regular triangulations.
        - `only_star`: Restricts to star triangulations.
        - `backend`: The backend used to check regularity. The options are any
            backend available for the [`is_solid`](./cone#is_solid) function of
            the [`Cone`](./cone) class. If not specified, it will be picked
            automatically.
        - `verbose`: Whether to print extra info from the TOPCOM command.

        **Returns:**
        The list of triangulations that differ by one bistellar flip from the
        current triangulation.

        **Example:**
        We construct a triangulation and find its neighbor triangulations.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]]).dual()
        t = p.triangulate()
        triangs = t.neighbor_triangulations()
        len(triangs) # Print how many triangulations it found
        # 263
        ```
        """
        # check for topcom bug
        if len(self.simplices())==1:
            warnings.warn("Triangulation.neighbor_triangulations called " + \
                            "for trivial triangulation (1 simplex)... " + \
                            "Returning []! Fix TOPCOM!")
            return []

        # optimized method for 2D fine neighbors
        if self.is_fine() and (self.dim()==2) and only_fine:
            return self._fine_neighbors_2d()

        # prep TOPCOM input
        pts_str = str([list(pt)+[1] for pt in self._pts_optimal])
        triang_str = str([list(s) for s in self._simplices])
        triang_str = triang_str.replace("[","{").replace("]","}")
        flips_str = "(-1)"

        topcom_input = pts_str + "[]" + triang_str + flips_str

        # prep TOPCOM
        topcom_bin = config.topcom_path + "topcom-points2flips"
        if verbose:
            cmd = (topcom_bin,"-v")
        else:
            cmd = (topcom_bin,)
        topcom = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  universal_newlines=True)

        # do the work and read output
        topcom_res, topcom_err = topcom.communicate(input=topcom_input)

        # check for errors
        if topcom.returncode != 0:
            print(f"TOPCOM exited with code {topcom.returncode}")
            if topcom.returncode == -9:
                print("This likely indicates an OOM error...")
                print("Try increasing memory (Docker Settings->Resources...)")
            return []

        if verbose:
            print(topcom_err)

        if len(topcom_res)==0:
            return []
        triangs_list = [ast.literal_eval(r) for r in\
                                                topcom_res.strip().split("\n")]

        # parse the outputs
        triangs = []
        for t in triangs_list:
            if not all(len(s)==self.dim()+1 for s in t):
                continue

            # construct and check triangulation
            tri = Triangulation(self._poly, self._pt_labels, simplices=t,
                                check_input_simplices=False)
            if only_fine and (not tri.is_fine()):
                continue
            if only_star and (not tri.is_star()):
                continue
            if only_regular and (not tri.is_regular(backend=backend)):
                continue

            # keep it :)
            triangs.append(tri)
        return triangs
    # aliases
    neighbors = neighbor_triangulations

    def random_flips(self,
                     N: int,
                     only_fine: bool = None,
                     only_regular: bool = None,
                     only_star: bool = None,
                     backend: str = None,
                     seed: int = None) -> "Triangulation":
        """
        **Description:**
        Returns a triangulation obtained by performing N random bistellar
        flips. The computation is performed with a modified version of TOPCOM.
        There is the option of limiting the flips to fine, regular, and star
        triangulations. An additional backend is used to check regularity, as
        checking this with TOPCOM is very slow for large polytopes.

        **Arguments:**
        - `N`: The number of bistellar flips to perform.
        - `only_fine`: Restricts to flips to fine triangulations. If not
            specified, it is set to True if the triangulation is fine, and
            False otherwise.
        - `only_regular`: Restricts the flips to regular triangulations. If not
            specified, it is set to True if the triangulation is regular, and
            False otherwise.
        - `only_star`: Restricts the flips to star triangulations. If not
            specified, it is set to True if the triangulation is star, and
            False otherwise.
        - `backend`: The backend used to check regularity. The options are any
            backend available for the [`is_solid`](./cone#is_solid) function of
            the [`Cone`](./cone) class. If not specified, it will be picked
            automatically.
        - `seed`: A seed for the random number generator. This can be used to
            obtain reproducible results.

        **Returns:**
        A new triangulation obtained by performing N random flips.

        **Example:**
        We construct a triangulation and perform 5 random flips to find a new
        triangulation.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]]).dual()
        t = p.triangulate()
        t.random_flips(5) # Takes a few seconds
        # A fine, star triangulation of a 4-dimensional point configuration
        # with 106 points in ZZ^4
        ```
        """
        # parse inputs
        if seed is not None:
            np.random.seed(seed)

        # take random flips
        curr_triang = self
        for n in range(N):
            neighbors = curr_triang.neighbor_triangulations(only_fine=False,\
                                                        only_regular=False,\
                                                        only_star=False)
            np.random.shuffle(neighbors)

            for t in neighbors:
                # check that the triangulation meets the requirements
                if only_fine and (not t.is_fine()):
                    continue
                if only_star and (not t.is_star()):
                    continue
                if only_regular and (not t.is_regular(backend=backend)):
                    continue

                # accept the triangulation
                curr_triang = t
                break
            else:
                raise RuntimeError("There was an error in the random walk.")

        return curr_triang

    def _fine_neighbors_2d(self,
                           only_regular: bool = False,
                           only_star: bool = False,
                           backend: str = None)->list["Triangulation"]:
        """
        **Description:**
        An optimized variant of neighbor_triangulations for triangulations that
        are:
            1) 2D (in dimension... ambient dimension doesn't matter)
            2) fine
            3) fine neighbors are desired
        In this case, _fine_neighbors_2d runs much quicker than the
        corresponding TOPCOM calculation

        **Arguments:**
        - `only_regular`: Restricts the to regular triangulations.
        - `only_star`: Restricts to star triangulations.
        - `backend`: The backend used to check regularity. The options are any
            backend available for the [`is_solid`](./cone#is_solid) function of
            the [`Cone`](./cone) class. If not specified, it will be picked
            automatically.

        **Returns:**
        The list of triangulations that differ by one diagonal flip from the
        current triangulation.
        """
        simps_set = [set(s) for s in self._simplices]
        triangs = []

        # for each pair of simplices
        for i, s1 in enumerate(simps_set):
            for _j,s2 in enumerate(simps_set[i+1:]):
                j = i+1+_j
                
                # check if they form a quadrilateral
                # (i.e., if they intersect along an edge)
                inter = s1&s2
                if len(inter)!=2:
                    continue
                
                # (and if the edge is 'internal')
                other = s1.union(s2)-inter
                if (sum(map(lambda ind:self._pts[ind], inter)) !=\
                    sum(map(lambda ind:self._pts[ind], other))).any():
                    continue
                
                # flip the inner diagonal
                flipped = list(map(lambda p: sorted(other|{p}), inter))
                new_simps = self._simplices.copy()
                new_simps[i] = flipped[0]
                new_simps[j] = flipped[1]

                # construct the triangulation
                tri = Triangulation(self._poly, self._pt_labels,\
                                    simplices=new_simps,\
                                    check_input_simplices=False)

                # check the triangulation
                if only_star and (not tri.is_star()):
                    continue
                if only_regular and (not tri.is_regular(backend=backend)):
                    continue

                # keep it :)
                triangs.append(tri)
        return triangs

    # misc
    # ====
    def gkz_phi(self) -> np.ndarray:
        """
        **Description:**
        Returns the GKZ phi vector of the triangulation. The $i$-th component is
        defined to be the sum of the volumes of the simplices that have the
        $i$-th point as a vertex.
        $\varphi^i=\sum_{\sigma\in\mathcal{T}|p_i\in\text{vert}(\sigma)}\text{vol}(\sigma)$

        **Arguments:**
        None.

        **Returns:**
        The GKZ phi vector of the triangulation.

        **Example:**
        We construct a triangulation and find its GKZ vector.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.gkz_phi()
        # array([18, 12,  9, 12, 12, 12, 15])
        ```
        """
        # check if we know the answer
        if self._gkz_phi is not None:
            return np.array(self._gkz_phi)

        # calculate the answer
        pts_ext = [list(pt)+[1,] for pt in self._pts_optimal]
        phi = np.zeros(len(pts_ext), dtype=int)

        for s in self._simplices:
            simp_vol = int(round(abs(np.linalg.det([pts_ext[i] for i in s]))))
            for i in s:
                phi[i] += simp_vol

        # return
        self._gkz_phi = phi
        return np.array(self._gkz_phi)

    def sr_ideal(self) -> tuple:
        """
        **Description:**
        Returns the Stanley-Reisner ideal if the triangulation is star.

        That is, find all sets of points which are not subsets of any simplex.
        The SR-ideal is generated by such subsets.

        N.B.: This function returns the *generators* of the ideal. I.e., we
        don't return multiples of the generators.

        E.g., take the simplicial complex
            [[1,2,3],[1,2,4],[2,3,4],[1,2,5]]
        It has the following sets of points not appearing together
            (3,5), (4,5), (1,3,4),(1,3,5),(1,4,5), (2,3,5), (2,4,5), (3,4,5)
        So, the SR ideal is generated by
            x3x5, x4x5, x1x3x4
        Don't include things like x2x3x5 since it is a multiple of x3x5.

        **Arguments:**
        None.

        **Returns:**
        The Stanley-Reisner ideal of the triangulation.

        **Example:**
        We construct a triangulation and find its SR ideal.
        ```python {3}
        p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
        t = p.triangulate()
        t.sr_ideal()
        # array([[1, 4, 5],
        #        [2, 3, 6]])
        ```
        """
        # check if we know the answer
        if self._sr_ideal is not None:
            return self._sr_ideal

        # check if we can answer
        if not self.is_star() or not self._is_fulldim:
            raise NotImplementedError("SR ideals can only be computed for "+\
                                      "full-dimensional star triangulations.")

        # prep-work
        points = set(range(len(self._pts))) - {self._origin_index}
        simplices = [[i for i in s if i != self._origin_index] for s in\
                                                            self.simplices()]

        simplex_tuples = []
        for dd in range(1,self.dim()+1):
            simplex_tuples.append(set())

            for s in simplices:
                simplex_tuples[-1].update(frozenset(tup) for tup in\
                                                itertools.combinations(s, dd))

        # calculate the SR ideal
        SR_ideal, checked = set(), set()

        for i in range(len(simplex_tuples)-1):
            for tup in simplex_tuples[i]:
                for j in points:
                    k = tup.union((j,))

                    # skip if already checked
                    if (k in checked) or (len(k)!=len(tup)+1):
                        continue
                    else:
                        checked.add(k)

                    if k in simplex_tuples[i+1]:
                        continue

                    # check it
                    in_SR = False
                    for order in range(1, i+1):
                        for t in itertools.combinations(tup, order):
                            if frozenset(t+(j,)) in SR_ideal:
                                in_SR = True
                                break
                        else:
                            # frozenset(t+(j,)) was not in SR_ideal for any t
                            # at this order
                            continue

                        # there was a t at this order such that
                        # frozenset(t+(j,)) was in SR_ideal for some 
                        break
                    else:
                        # frozenset(t+(j,)) was not in SR_ideal for any order
                        SR_ideal.add(k)

        # return
        self._sr_ideal = [tuple(sorted(s)) for s in SR_ideal]
        self._sr_ideal = tuple(sorted(self._sr_ideal, key=lambda x:(len(x),x)))
        return self._sr_ideal

def _to_star(triang: Triangulation) -> np.ndarray:
    """
    **Description:**
    Turns a triangulation into a star triangulation by deleting internal lines
    and connecting all points to the origin.

    :::note
    This function is not intended to be called by the end user. Instead, it is
    used by the [`Triangulation`](./triangulation) class when needed.
    :::

    :::important
    This function is only reliable for triangulations of reflexive polytopes
    and may produce invalid triangulations for other polytopes.
    :::

    **Arguments:**
    - `triang`: The triangulation to convert to star.

    **Returns:**
    Nothing.
    """
    # reflexivity check
    assert triang._poly.is_reflexive()

    # preliminary
    # (use boundary pts b/c pts interior to facets aren't normally included)
    facets = [[triang._pts_dict[tuple(pt)] for pt in f.boundary_points()]\
                                                for f in triang._poly.facets()]
    dim = len(triang._simplices[0]) - 1

    # map the simplices to being star
    star_triang = []

    for facet in facets:
        for simp in np.array(triang._simplices):
            overlap = simp[np.isin(simp, facet)].tolist()
            if len(overlap) == dim:
                star_triang.append([triang._origin_index] + overlap)

    # update triang
    triang._simplices = np.array(sorted([sorted(s) for s in star_triang]))

def _qhull_triangulate(points: ArrayLike, heights: ArrayLike) -> np.ndarray:
    """
    **Description:**
    Computes a regular triangulation using QHull.

    :::note
    This function is not intended to be called by the end user. Instead, it is
    used by the [`Triangulation`](./triangulation) class when using QHull as
    the backend.
    :::

    **Arguments:**
    - `points`: A list of points.
    - `heights`: A list of heights defining the regular triangulation.

    **Returns:**
    A list of simplices defining a regular triangulation.

    **Example:**
    This function is not intended to be directly used, but it is used in the
    following example. We construct a triangulation using QHull.
    ```python {2}
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
    p.triangulate(backend="qhull")
    # A fine, star triangulation of a 4-dimensional point configuration with 7
    # points in ZZ^4
    ```
    """
    lifted_points = [tuple(points[i]) + (heights[i],) for i in\
                                                            range(len(points))]
    hull = ConvexHull(lifted_points)

    # We first pick the lower facets of the convex hull
    low_fac = [hull.simplices[n] for n,nn in enumerate(hull.equations)\
                    if nn[-2] < 0] # The -2 component is the lifting dimension

    # Then we only take the faces that project to full-dimensional simplices
    # in the original point configuration
    lifted_points = [pt[:-1] + (1,) for pt in lifted_points]
    simp = [s for s in low_fac if int(round(np.linalg.det([lifted_points[i]\
                                                        for i in s]))) != 0]

    return np.array(sorted([sorted(s) for s in simp]))


def _cgal_triangulate(points: ArrayLike, heights: ArrayLike) -> np.ndarray:
    """
    **Description:**
    Computes a regular triangulation using CGAL.

    :::note
    This function is not intended to be called by the end user. Instead, it is
    used by the [`Triangulation`](./triangulation) class when using CGAL as the
    backend.
    :::

    **Arguments:**
    - `points`: A list of points.
    - `heights`: A list of heights defining the regular triangulation.

    **Returns:**
    A list of simplices defining a regular triangulation.

    **Example:**
    This function is not intended to be directly used, but it is used in the
    following example. We construct a triangulation using CGAL.
    ```python {2}
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
    p.triangulate(backend="cgal")
    # A fine, star triangulation of a 4-dimensional point configuration with 7
    # points in ZZ^4
    ```
    """
    # input parsing
    dim = points.shape[1]

    pts_str = str([list(pt) for pt in points])
    heights_str = str(list(heights)).replace("[", "(").replace("]", ")")

    # pass the command to CGAL
    cgal_bin = config.cgal_path
    cgal_bin += (f"/cgal-triangulate-{dim}d" if dim in (2,3,4,5)\
                                                    else "cgal-triangulate")
    cgal = subprocess.Popen((cgal_bin,), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)

    # read/parse outputs
    cgal_res, cgal_err = cgal.communicate(input=pts_str+heights_str)

    if cgal_err != "":
        raise RuntimeError(f"CGAL error: {cgal_err}")

    try:
        simp = ast.literal_eval(cgal_res)
    except:
        raise RuntimeError("Error: Failed to parse CGAL output.")

    # return
    return np.array(sorted([sorted(s) for s in simp]))


def _topcom_triangulate(points: ArrayLike) -> np.ndarray:
    """
    **Description:**
    Computes the placing/pushing triangulation using TOPCOM.

    :::note
    This function is not intended to be called by the end user. Instead, it is
    used by the [`Triangulation`](./triangulation) class when using TOPCOM as
    the backend.
    :::

    **Arguments:**
    - `points`: A list of points.

    **Returns:**
    A list of simplices defining a triangulation.

    **Example:**
    This function is not intended to be directly used, but it is used in the
    following example. We construct a triangulation using TOMCOM.
    ```python {2}
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-6,-9]])
    p.triangulate(backend="topcom")
    # A fine, star triangulation of a 4-dimensional point configuration with 7
    # points in ZZ^4
    ```
    """
    # prep
    topcom_bin = config.topcom_path + "/topcom-points2finetriang"
    topcom = subprocess.Popen((topcom_bin, "--regular"), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)

    # do the work
    pts_str = str([list(pt)+[1] for pt in points])
    topcom_res, topcom_err = topcom.communicate(input=pts_str+"[]")

    # parse the output
    try:
        simp = ast.literal_eval(topcom_res.replace("{", "[").replace("}", "]"))
    except:
        raise RuntimeError("Error: Failed to parse TOPCOM output. "
                           f"\nstdout: {topcom_res} \nstderr: {topcom_err}")

    return np.array(sorted([sorted(s) for s in simp]))


def all_triangulations(poly: "Polytope",
                       pts: ArrayLike,
                       only_fine: bool = False,
                       only_regular: bool = False,
                       only_star: bool = False,
                       star_origin: int = None,
                       backend: str = None,
                       raw_output: bool = False) -> "generator[Triangulation]":
    """
    **Description:**
    Computes all triangulations of the input point configuration using TOPCOM.
    There is the option to only compute fine, regular or fine triangulations.

    :::note
    This function is not intended to be called by the end user. Instead, it is
    used by the [`all_triangulations`](./polytope#all_triangulations) function
    of the [`Polytope`](./polytope) class.
    :::

    **Arguments:**
    - `poly`: The ambient polytope.
    - `pts`: The list of points to be triangulated. Specified by labels.
    - `only_fine`: Restricts to only fine triangulations.
    - `only_regular`: Restricts to only regular triangulations.
    - `only_star`: Restricts to only star triangulations.
    - `star_origin`: The index of the point that will be used as the star
        origin. If the polytope is reflexive this is set to 0, but otherwise it
        must be specified.
    - `backend`: The optimizer used to check regularity computation. The
        available options are "topcom" and the backends of the
        [`is_solid`](./cone#is_solid) function of the [`Cone`](./cone) class.
        If not specified, it will be picked automatically. Note that using
        TOPCOM to check regularity is slower.
    - `raw_output`: Return the triangulations as lists of simplices instead of
        as Triangulation objects.

    **Returns:**
    A generator of [`Triangulation`](./triangulation) objects with the
    specified properties. If `raw_output` is set to True then numpy arrays are
    used instead.

    **Example:**
    This function is not intended to be directly used, but it is used in the
    following example. We construct a polytope and find all of its
    triangulations. We try picking different restrictions and see how the number
    of triangulations changes.
    ```python {2,7,9}
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-2,-1,-1],[-2,-1,-1,-1]])
    g = p.all_triangulations()
    next(g) # Takes some time while TOPCOM finds all the triangulations
    # A fine, regular, star triangulation of a 4-dimensional point
    # configuration with 7 points in ZZ^4
    next(g) # Produces the next triangulation immediately
    # A fine, regular, star triangulation of a 4-dimensional point
    # configuration with 7 points in ZZ^4
    len(p.all_triangulations(as_list=True)) # Number of fine, regular, star triangulations
    # 2
    len(p.all_triangulations(only_regular=False, only_star=False, only_fine=False, as_list=True) )# Number of triangularions, no matter if fine, regular, or star
    # 6
    ```
    """
    # input checking/parsing
    if len(pts) == 0:
        raise ValueError("List of points cannot be empty.")

    if only_star and star_origin is None:
        raise ValueError("The star_origin parameter must be specified when "
                         "restricting to star triangulations.")

    # ensure points are appropriately sorted (for Triangulation inputs)
    triang_pts = poly.points(which=pts)
    if raw_output:
        backend = "topcom"

    # if not full-dimenstional, find better representation
    # (only performs affine transformation, so can treat the new points as if
    # they were the original ones)
    dim = np.linalg.matrix_rank([tuple(pt)+(1,) for pt in triang_pts])-1
    if dim == points.shape[1]:
        optimal_pts = points
    else:
        optimal_pts = lll_reduce([pt - points[0] for pt in triang_pts])[:,-dim:]

    # prep for TOPCOM
    topcom_bin = config.topcom_path
    if only_fine:
        topcom_bin += "topcom-points2allfinetriangs"
    else:
        topcom_bin += "topcom-points2alltriangs"

    reg_arg = ("--regular",) if backend=="topcom" and only_regular else ()
    topcom = subprocess.Popen((topcom_bin,)+reg_arg,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)

    # do the work
    pts_str = str([list(pt)+[1] for pt in optimal_pts])
    topcom_res, topcom_err = topcom.communicate(input=pts_str+"[]")

    #parse the output
    try:
        triangs = [ast.literal_eval("["+ t.replace("{","[").replace("}","]") +\
                        "]") for t in re.findall(r"\{([^\:]*)\}", topcom_res)]
    except:
        raise RuntimeError("Error: Failed to parse TOPCOM output. "
                           f"\nstdout: {topcom_res} \nstderr: {topcom_err}")

    # sort the triangs
    srt_triangs = [np.array(sorted([sorted(s) for s in t])) for t in triangs
                    if (not only_star or all(star_origin in ss for ss in t))]

    # return the output
    for t in srt_triangs:
        if raw_output:
            yield t
            continue
        tri = Triangulation(poly, pts, simplices=t, make_star=False,
                                                check_input_simplices=False)
        if not only_regular or tri.is_regular(backend=backend):
            yield tri

def random_triangulations_fast_generator(poly: "Polytope",
                                         pts: ArrayLike,
                                         N: int = None,
                                         c: float = 0.2,
                                         max_retries: int = 500,
                                         make_star: bool = False,
                                         only_fine: bool = True,
                                         backend: str = "cgal",
                                         seed: int = None,
                                         verbosity: int = 0) -> "generator[Triangulation]":
    """
    Constructs pseudorandom regular (optionally fine and star) triangulations
    of a given point set. This is done by picking random heights around the
    Delaunay heights from a Gaussian distribution.

    :::note
    This function is not intended to be called by the end user. Instead, it is
    used by the
    [`random_triangulations_fast`](./polytope#random_triangulations_fast)
    function of the [`Polytope`](./polytope) class.
    :::

    :::caution important
    This function produces random triangulations very quickly, but it does not
    produce a fair sample. When a fair sampling is required the
    [`random_triangulations_fair`](./polytope#random_triangulations_fair)
    function should be used.
    :::

    **Arguments:**
    - `poly`: The ambient polytope.
    - `pts`: The list of points to be triangulated. Specified by labels.
    - `N`: Number of desired unique triangulations. If not specified, it will
        generate as many triangulations as it can find until it has to retry
        more than max_retries times to obtain a new triangulation.
    - `c`: A contant used as the standard deviation of the Gaussian
        distribution used to pick the heights. A larger c results in a wider
        range of possible triangulations, but with a larger fraction of them
        being non-fine, which slows down the process when using only_fine=True.
    - `max_retries`: Maximum number of attempts to obtain a new triangulation
        before the process is terminated.
    - `make_star`: Converts the obtained triangulations into star
        triangulations.
    - `only_fine`: Restricts to fine triangulations.
    - `backend`: Specifies the backend used to compute the triangulation. The
        available options are "cgal" and "qhull".
    - `seed`: A seed for the random number generator. This can be used to
        obtain reproducible results.
    - `verbosity`: The verbosity level.

    **Returns:**
    A generator of [`Triangulation`](./triangulation) objects with the
    specified properties.

    **Example:**
    This function is not intended to be directly used, but it is used in the
    following example. We construct a polytope and find some random
    triangulations. The triangulations are obtained very quicly, but they are
    not a fair sample of the space of triangulations. For a fair sample, the
    [`random_triangulations_fair`](./polytope#random_triangulations_fair)
    function should be used.
    ```python {2,7}
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]]).dual()
    g = p.random_triangulations_fast()
    next(g) # Runs very quickly
    # A fine, regular, star triangulation of a 4-dimensional point
    # configuration with 106 points in ZZ^4
    next(g) # Keeps producing triangulations until it has trouble finding more
    # A fine, regular, star triangulation of a 4-dimensional point
    # configuration with 106 points in ZZ^4
    rand_triangs = p.random_triangulations_fast(N=10, as_list=True) # Produces the list of 10 triangulations very quickly
    ```
    """
    # parse inputs
    if seed is not None:
        np.random.seed(seed)

    triang_hashes = set()
    n_retries = 0
    while True:
        if n_retries >= max_retries:
            if verbosity>0:
                print("random_triangulations_fast_generator: Hit max_retries... returning")
            return
        if (N is not None) and (len(triang_hashes) >= N):
            if verbosity>1:
                print("random_triangulations_fast_generator: Generated enough triangulations... returning")
            return

        # generate random heights, make the triangulation
        heights= [pt.dot(pt) + np.random.normal(0,c) for pt in poly.points(which=pts)]
        t = Triangulation(poly, pts, heights=heights,
                          make_star=make_star, backend=backend,
                          check_heights=False)

        # check if it's good
        if only_fine and (not t.is_fine()):
            n_retries += 1
            continue

        # check that the heights aren't on a wall of the secondary cone
        t.check_heights(verbosity-1)

        h = hash(t)
        if h in triang_hashes:
            n_retries += 1
            continue

        # it is good!
        triang_hashes.add(h)
        n_retries = 0
        yield t

def random_triangulations_fair_generator(poly: "Polytope",
                                         pts: ArrayLike,
                                         N: int = None,
                                         n_walk: int = 10,
                                         n_flip: int = 10,
                                         initial_walk_steps: int = 20,
                                         walk_step_size: float = 1e-2,
                                         max_steps_to_wall: int = 10,
                                         fine_tune_steps: int = 8,
                                         max_retries: int = 50,
                                         make_star: bool = False,
                                         backend: str = "cgal",
                                         seed: int = None) -> "generator[Triangulation]":
    """
    **Description:**
    Constructs pseudorandom regular (optionally star) triangulations of a given
    point set. Implements Algorithm \#3 from the paper
    *Bounding the Kreuzer-Skarke Landscape* by Mehmet Demirtas, Liam
    McAllister, and Andres Rios-Tascon.
    [arXiv:2008.01730](https://arxiv.org/abs/2008.01730)

    This is a Markov chain Monte Carlo algorithm that involves taking random
    walks inside the subset of the secondary fan corresponding to fine
    triangulations and performing random flips. For details, please see Section
    4.1 in the paper.

    :::note notes
    - This function is not intended to be called by the end user. Instead, it
        is used by the 
        [`random_triangulations_fair`](./polytope#random_triangulations_fair)
        function of the [`Polytope`](./polytope) class.
    - This function is designed mainly for large polytopes where sampling
        triangulations is challenging. When small polytopes are used it is
        likely to get stuck.
    :::

    **Arguments:**
    - `poly`: The ambient polytope.
    - `pts`: The list of points to be triangulated. Specified by labels.
    - `N`: Number of desired unique triangulations. If not specified, it will
        generate as many triangulations as it can find until it has to retry
        more than max_retries times to obtain a new triangulation.
    - `n_walk`: Number of hit-and-run steps per triangulation.
    - `n_flip`: Number of random flips performed per triangulation.
    - `initial_walk_steps`: Number of hit-and-run steps to take before starting
        to record triangulations. Small values may result in a bias towards
        Delaunay-like triangulations.
    - `walk_step_size`: Determines size of random steps taken in the secondary
        fan. Algorithm may stall if too small.
    - `max_steps_to_wall`: Maximum number of steps to take towards a wall of
        the subset of the secondary fan that correspond to fine triangulations.
        If a wall is not found, a new random direction is selected. Setting
        this to be very large (>100) reduces performance. If this, or
        walk_step_size, is set to be too low, the algorithm may stall.
    - `fine_tune_steps`: Number of steps to determine the location of a wall.
        Decreasing improves performance, but might result in biased samples.
    - `max_retries`: Maximum number of attempts to obtain a new triangulation
        before the process is terminated.
    - `make_star`: Converts the obtained triangulations into star
        triangulations.
    - `backend`: Specifies the backend used to compute the triangulation. The
        available options are "cgal" and "qhull".
    - `seed`: A seed for the random number generator. This can be used to
        obtain reproducible results.

    **Returns:**
    A generator of [`Triangulation`](./triangulation) objects with the
    specified properties.

    **Example:**
    This function is not intended to be directly used, but it is used in the
    following example. We construct a polytope and find some random
    triangulations. The computation takes considerable time, but they should be
    a fair sample from the full set of triangulations (if the parameters are
    chosen correctly). For (some) machine learning purposes or when the
    fairness of the sample is not crucial, the
    [`random_triangulations_fast`](./polytope#random_triangulations_fast)
    function should be used instead.
    ```python {2,7}
    p = Polytope([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[-1,-1,-1,-1]]).dual()
    g = p.random_triangulations_fast()
    next(g) # Takes a long time (around a minute)
    # A fine, regular, star triangulation of a 4-dimensional point configuration with 106 points in ZZ^4
    next(g) # Takes slightly shorter (still around a minute)
    # A fine, regular, star triangulation of a 4-dimensional point
    # configuration with 106 points in ZZ^4
    rand_triangs = p.random_triangulations_fair(N=10, as_list=True) # Produces the list of 10 triangulations, but takes a long time (around 10 minutes)
    ```
    It is worth noting that the time it takes to obtain each triangulation
    varies very significantly on the parameters used. The function tries to
    guess reasonable parameters, but it is better to adjust them to your
    desired balance between speed and fairness of the sampling.
    """
    # input parsing
    traing_pts = poly.points(which=pts)
    num_points = len(pts)

    dim = np.linalg.matrix_rank([tuple(pt)+(1,) for pt in traing_pts])-1
    if dim != traing_pts.shape[1]:
        raise Exception("Point configuration must be full-dimensional.")

    if seed is not None:
        np.random.seed(seed)
    
    # Obtain random Delaunay triangulation by picking random point as origin
    rand_ind = np.random.randint(0,len(pts))
    points_shifted = [p-traing_pts[rand_ind] for p in traing_pts]

    delaunay_heights = [walk_step_size*(np.dot(p,p)) for p in points_shifted]
    start_pt = delaunay_heights
    old_pt = start_pt

    step_size = walk_step_size*np.mean(delaunay_heights)
    
    # initialize for MCMC
    step_ctr = 0            # total # of steps taken
    step_per_tri_ctr = 0    # # of steps taken for given triangulation
    
    n_retries = 0
    triang_hashes = set()

    # do the work
    while True:
        # check if we're done
        if n_retries>=max_retries:
            break
        if (N is not None) and (len(triang_hashes)>N):
            break

        # find a wall
        # (move along random direction until we hit a non-fine triangulation)
        outside_bounds = False
        for _ in range(max_retries):
            in_pt = old_pt

            # find random direction
            random_dir = np.random.normal(size=num_points)
            random_dir = random_dir / np.linalg.norm(random_dir)

            # take steps
            for __ in range(max_steps_to_wall):
                new_pt = in_pt + random_dir*step_size
                temp_tri = Triangulation(poly, pts, heights=new_pt,
                                            make_star=False, backend=backend,
                                            verbosity=0)

                # check triang
                if temp_tri.is_fine():
                    in_pt = new_pt
                else:
                    out_pt = new_pt
                    outside_bounds = True
                    break

            if outside_bounds:
                break

        # break loop it it can't find any new wall after max_retries
        if not outside_bounds:
            print("Couldn't find wall.")
            break

        # Find the location of the boundary
        fine_tune_ctr = 0
        in_pt_found = False
        while (fine_tune_ctr<fine_tune_steps) or (not in_pt_found):
            new_pt = (in_pt+out_pt)/2
            temp_tri = Triangulation(poly, pts, heights=new_pt,
                                            make_star=False, backend=backend,
                                            verbosity=0)

            # check triang
            if temp_tri.is_fine():
                in_pt = new_pt
                in_pt_found = True
            else:
                out_pt = new_pt

            fine_tune_ctr += 1

        # Take a random walk step
        in_pt = in_pt/np.linalg.norm(in_pt)
        random_coef = np.random.uniform(0,1)
        new_pt =    (random_coef*np.array(old_pt) +\
                 (1-random_coef)*np.array(in_pt))

        # after enough steps are taken, move on to random flips
        if (step_ctr>initial_walk_steps) and (step_per_tri_ctr>=n_walk):
            flip_seed_tri =Triangulation(poly, pts, heights=new_pt,
                                        make_star=make_star, backend=backend,
                                        verbosity=0)

            # take flips
            if n_flip > 0:
                temp_tri = flip_seed_tri.random_flips(n_flip, only_fine=True,
                                                      only_regular=True,
                                                      only_star=True)
            else:
                temp_tri = flip_seed_tri

            # record triangulation
            h = hash(temp_tri)
            if h in triang_hashes:
                n_retries += 1
                continue
            triang_hashes.add(h)

            n_retries = 0
            step_per_tri_ctr = 0

            yield temp_tri

        # update old point
        old_pt = new_pt/np.linalg.norm(new_pt)

        # update counters
        step_ctr += 1
        step_per_tri_ctr += 1

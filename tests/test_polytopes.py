from cytools import Polytope

def test_points():
    p = Polytope([[1, 0], [0, 1], [-1, 0], [0, -1]])

    assert p.points().tolist() == [[1, 0], [0, 1], [-1, 0], [0, -1]]

# Square Tubing End Cap

```python
from build123d import export_stl

from main import Params, make_end_cap
from common.utils import show_svg
```


```python
params = Params()
part = make_end_cap(params)

show_svg(part, wireframe=True)
show(part)
```


    
![svg](.assets/README_1_0.svg)
    


    +





    <cad_viewer_widget.widget.CadViewer at 0x7f40d2a5dd30>



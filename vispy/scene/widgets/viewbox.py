# -*- coding: utf-8 -*-
# Copyright (c) 2014, Vispy Development Team.
# Distributed under the (new) BSD License. See LICENSE.txt for more info.

from __future__ import division

import numpy as np

from ..transforms import STTransform
from .widget import Widget
from ..subscene import SubScene


class ViewBox(Widget):
    """ Provides a rectangular window to which its subscene is rendered
    """

    def __init__(self, *args, **kwds):
        Widget.__init__(self, *args, **kwds)

        # Background color of this viewbox. Used in glClear()
        self._bgcolor = (0.0, 0.0, 0.0, 1.0)

        # Init preferred method to provided a pixel grid
        self._preferred_clip_method = 'none'

        # Each viewbox has a scene widget, which has a transform that
        # represents the transformation imposed by camera.
        self._scene = SubScene()
        self._scene.parent = self

    @property
    def bgcolor(self):
        """ The background color of the scene. within the viewbox.
        """
        return self._bgcolor

    @bgcolor.setter
    def bgcolor(self, value):
        # Check / convert
        value = [float(v) for v in value]
        if len(value) < 3:
            raise ValueError('bgcolor must be 3 or 4 floats.')
        elif len(value) == 3:
            value.append(1.0)
        elif len(value) == 4:
            pass
        else:
            raise ValueError('bgcolor must be 3 or 4 floats.')
        # Set
        self._bgcolor = tuple(value)

    @property
    def scene(self):
        """ The root entity of the subscene of this viewbox. This entity
        takes care of the transformation imposed by the camera of the
        viewbox.
        """
        return self._scene

    @property
    def camera(self):
        """ The camera associated with this viewbox. Can be None if there
        are no cameras in the scene.
        """
        return self.scene.camera

    @camera.setter
    def camera(self, cam):
        """ Get/set the camera of the scene. Equivalent to scene.camera.
        """
        raise RuntimeError('ViewBox does no longer have a camera. '
                           'Use viewbox.scene instead')
    
    def add(self, entity):
        """ Add an Entity to the scene for this ViewBox. 
        
        This is a convenience method equivalent to 
        `entity.add_parent(viewbox.scene)`
        """
        entity.add_parent(self.scene)

    @property
    def preferred_clip_method(self):
        """ The preferred way to clip the boundaries of the viewbox.

        There are three possible ways that the viewbox can perform
        clipping:

        * 'none' - do not perform clipping. The default for now.
        * 'fragment' - clipping in the fragment shader TODO
        * 'viewport' - use glViewPort to provide a clipped sub-grid
          onto the parent pixel grid, if possible.
        * 'fbo' - use an FBO to draw the subscene to a texture, and
          then render the texture in the parent scene.

        Restrictions and considerations
        -------------------------------

        The 'viewport' method requires that the transformation (from
        the pixel grid to this viewbox) is translate+scale only. If
        this is not the case, the method falls back to the default.

        The 'fbo' method is convenient when the result of the viewbox
        should be reused. Otherwise the overhead can be significant and
        the image can get slightly blurry if the transformations do
        not match.

        It is possible to have a graph with multiple stacked viewboxes
        which each use different methods (subject to the above
        restrictions).

        """
        return self._preferred_clip_method

    @preferred_clip_method.setter
    def preferred_clip_method(self, value):
        valid_methods = ('none', 'fragment', 'viewport', 'fbo')
        if value not in valid_methods:
            t = 'preferred_clip_method should be in %s' % str(valid_methods)
            raise ValueError((t + ', not %r') % value)
        self._preferred_clip_method = value

    def draw(self, event):
        """ Draw the viewbox.

        This does not really draw *this* object, but prepare for drawing
        our the subscene. In particular, here we calculate the transform
        needed to project the subscene in our viewbox rectangle. Also
        we handle setting a viewport if requested.
        """

        # todo: we could consider including some padding
        # so that we have room *inside* the viewbox to draw ticks and stuff

        # --  Calculate viewbox transformation

        # Get the sign of the camera transform of the parent scene. We
        # cannot look at full_transform, since the ViewBox may just be
        # really upside down (intended). The camera transform defines
        # the direction of the dimensions of the coordinate frame.
        # todo: get this sign information in a more effective manner
        # than we can probably also get rid of storing viewbox on event!
        parent_viewbox = event.viewbox
        if parent_viewbox:
            s = parent_viewbox.camera.get_projection(event) * STTransform()
            signx = 1 if s.scale[0] > 0 else -1
            signy = 1 if s.scale[1] > 0 else -1
        else:
            signx, signy = 1, 1

        # Determine transformation to make NDC coords (-1..1) map to
        # the viewbox region. The translation is equivalent to doing a
        # (1, 1) shift *after* the scale.
        size = self.size
        trans = STTransform()
        trans.scale = signx * size[0] / 2, signy * size[1] / 2
        trans.translate = size[0] / 2, size[1] / 2

        # Set this transform at the scene
        self.scene.viewbox_transform = trans

        # -- Calculate resolution

        # Get current transform and calculate the 'scale' of the viewbox
        transform = event.full_transform
        p0, p1 = transform.map((0, 0)), transform.map(size)
        sx, sy = p1[0] - p0[0], p1[1] - p0[1]

        # From the viewbox scale, we can calculate the resolution. Note that
        # the viewbox scale (sx, sy) applies to the root.
        # todo: we should probably take rotation into account here ...
        canvas_res = event.canvas.size  # root resolution
        w = abs(sx * canvas_res[0] * 0.5)
        h = abs(sy * canvas_res[1] * 0.5)

        # Set resolution (note that resolution can be non-integer)
        self._resolution = w, h
        #print(getattr(self, '_name', ''), w, h)

        # -- Get user clipping preference

        prefer = self.preferred_clip_method
        assert prefer in ('none', 'fragment', 'viewport', 'fbo')
        viewport, fbo = None, None

        if prefer == 'none':
            pass
        elif prefer == 'fragment':
            raise NotImplementedError('No fragment shader clipping yet.')
        elif prefer == 'viewport':
            viewport = self._prepare_viewport(event, w, h, signx, signy)
        elif prefer == 'fbo':
            fbo = self._prepare_fbo(event)

        # -- Draw

        event.push_viewbox(self)

        if fbo:
            # Push FBO
            shape = fbo.color_buffer.shape
            rect = 0, 0, shape[1], shape[0]
            transform = event.full_transform * self.scene.viewbox_transform
            event.push_fbo(rect, fbo, transform.inverse())
            #print(self._name, (event.render_transform #
            #                   self.scene.viewbox_transform).simplify())
            # Clear bg color (handy for dev)
            from vispy.gloo import gl
            clrs = {'': (0.1, 0.1, 0.1),
                    'vb1': (0.2, 0, 0),
                    'vb11': (0.2, 0, 0.1), 'vb12': (0.2, 0, 0.2),
                    'vb2': (0, 0.2, 0),
                    'vb21': (0, 0.2, 0.1), 'vb22': (0, 0.2, 0.2)}
            clr = clrs[getattr(self, '_name', '')]
            # clrs[''] or clrs[getattr(self,'_name', '')]
            gl.glClearColor(clr[0], clr[1], clr[2], 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            # Process childen
            self.scene.draw(event)
            # Pop FBO and now draw the result
            event.pop_fbo()
            self._myprogram.draw(gl.GL_TRIANGLE_STRIP)

        elif viewport:
            # Push viewport, draw, pop it
            event.push_viewport(viewport)
            self.scene.draw(event)
            event.pop_viewport()

        else:
            # Just draw
            # todo: invoke fragment shader clipping
            self.scene.draw(event)

        event.pop_viewbox()

    def _prepare_viewport(self, event, w, h, signx, signy):
        # Get whether the transform to here is translate-scale only
        rtransform = event.render_transform
        p0 = rtransform.map((0, 0))
        px, py = rtransform.map((1, 0)), rtransform.map((0, 1))
        dx, dy = py[0] - p0[0], px[1] - p0[1]

        # Does the transform look scale-trans only?
        if not (dx == 0 and dy == 0):
            return None

        # Transform from NDC to viewport coordinates
        canvas_res = event.canvas.size
        tx, ty = py[0], px[1]  # Translation of unit vector
        x = (signx*0.5 + 0.5 + tx) * canvas_res[0] * 0.5
        y = (signy*0.5 + 0.5 + ty) * canvas_res[1] * 0.5

        # Round
        return int(x+0.5), int(y+0.5), int(w+0.5), int(h+0.5)

    def _prepare_fbo(self, event):
        """ Draw the viewbox via an FBO. This method can be applied
        in any situation, regardless of the transformations to this
        viewbox.

        TODO:
        Right now, this implementation create a program, texture and FBO
        on *each* draw, because it does not work otherwise. This is probably
        a bug in gloo that prevents using two FBO's / programs at the same
        time.

        Also, we use plain gloo and calculate the transformation
        ourselves, assuming 2D only. Eventually we should just use the
        transform of self. I could not get that to work, probably
        because I do not understand the component system yet.
        """

        from vispy.gloo import gl
        from vispy import gloo

        render_vertex = """
            attribute vec3 a_position;
            attribute vec2 a_texcoord;
            varying vec2 v_texcoord;
            void main()
            {
                gl_Position = vec4(a_position, 1.0);
                v_texcoord = a_texcoord;
            }
        """

        render_fragment = """
            uniform sampler2D u_texture;
            varying vec2 v_texcoord;
            void main()
            {
                vec4 v = texture2D(u_texture, v_texcoord);
                gl_FragColor = vec4(v.rgb, 1.0);
            }
        """

        # todo: don't do this on every draw
        if True:
            # Create program
            self._myprogram = gloo.Program(render_vertex, render_fragment)
            # Create texture
            self._tex = gloo.Texture2D(shape=(10, 10, 4), dtype=np.uint8)
            self._tex.interpolation = gl.GL_LINEAR
            self._myprogram['u_texture'] = self._tex
            # Create texcoords and vertices
            texcoord = np.array([[0, 0], [1, 0], [0, 1], [1, 1]],
                                dtype=np.float32)
            position = np.zeros((4, 3), np.float32)
            self._myprogram['a_texcoord'] = gloo.VertexBuffer(texcoord)
            self._myprogram['a_position'] = self._vert = \
                gloo.VertexBuffer(position)

        # Get fbo, ensure it exists
        fbo = getattr(self, '_fbo', None)
        if True:  # fbo is None:
            self._fbo = 4
            self._fbo = fbo = gloo.FrameBuffer(self._tex,
                                               depth=gloo.DepthBuffer((10,
                                                                       10)))

        # Set texture coords to make the texture be drawn in the right place
        # Note that we would just use -1..1 if we would use a Visual.
        # Note that we need the viewbox transform here!
        coords = (-1, -1, 0), (1, 1, 0)
        transform = event.render_transform * self.scene.viewbox_transform
        coords = [transform.map(c) for c in coords]
        x1, y1, z = coords[0][:3]
        x2, y2, z = coords[1][:3]
        vertices = np.array([[x1, y1, z], [x2, y1, z],
                             [x1, y2, z], [x2, y2, z]],
                            np.float32)
        self._vert.set_data(vertices)

        # Set fbo size (mind that this is set using shape!)
        # +1 to create delibirate smoothing
        resolution = [int(i+0.5+1) for i in self._resolution]  # set in draw()
        shape = resolution[1], resolution[0]
        fbo.color_buffer.resize(shape+(4,))
        fbo.depth_buffer.resize(shape)

        return fbo
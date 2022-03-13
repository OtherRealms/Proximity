
from typing import Collection
import bpy,os
from bpy.types import Operator,Panel
from bpy.props import*
from math import sqrt,ceil

pillow_check = False
additional_message = ""
is_ready = [False]

try:
    import PIL
    from PIL import Image,ImageFilter
    

    print('Importing PIL')
    version_list = PIL.PILLOW_VERSION.split('.')
    version = [0,0,0]
    for i in range(0, len(version_list)): 
        version[i] = int(version_list [i]) 
    if tuple(version) < (8,1,0):
        pillow_check = False
    else:
        pillow_check = True

except ModuleNotFoundError as err:
    pillow_check = False
    print("Couldn't import PIL")

class PROXIMITY_OT_install_PILLOW(Operator):
    bl_idname = "proximity.install_pillow"
    bl_description = "Download and install PILLOW library"
    bl_label = "Install PILLOW"

    def execute(self,context):
        import subprocess
        import sys
        from pathlib import Path
        #pip install Pillow==8.1.0

        # OS independent (Windows: bin\python.exe; Mac/Linux: bin/python3.7m)
        try:
            global additional_message ,pillow_check
            py_path = Path(sys.prefix) / "bin"
            # first file that starts with "python" in "bin" dir
            py_exec = next(py_path.glob("python*"))
            # ensure pip is installed & update
            subprocess.call([str(py_exec), "-m", "ensurepip"])
            subprocess.call([str(py_exec), "-m", "pip", "install","--user","--upgrade", "pip"])
            subprocess.call([str(py_exec),"-m", "pip","install", "--upgrade", "Pillow"])#"--user",
            # install dependencies using pip
            self.report({'INFO'},'Pillow Library Successfully Installed')
            import PIL
            additional_message = "Blender needs to be restarted!"
            pillow_check = True
            
        except:
            self.report({'ERROR'},"Could not install, check console for error")
            additional_message = "Install error:" + str(sys.exc_info()[0])
            print("Install error:", sys.exc_info()[0])
            raise 

        return {'FINISHED'}

class PROXIMITY_OT_bake(Operator):
    bl_idname = "proximity.bake"
    bl_description = "Bake frame range to greyscale PNG image sequence"
    bl_label = "Bake"

    grp : IntProperty(options={'HIDDEN'})
    vertex_grp : EnumProperty(name = 'Vertex Group', items = (('vertex_group_threshold','THRESHOLD','THRESHOLD'),('vertex_group_ranged','RANGED','RANGED')))
    bakeMethod : EnumProperty(name = 'Method', items = (('Image Sequence','Image Sequence','Image Sequence'),('Pixel Sequence','Pixel Sequence','Creates a single image with an X pixel per frame, Y pixel per object')))
    temporal_smooth : BoolProperty(name = "Temporal Smoothing",description = "Blender frames to reduce flicker")
    vert_grp_name = ""
    rounds = 0
    filter_grp= None
    filter_id = None
    vertex_grp_id =0

    obj = None
    collection = None
    mode = ''
    directory = ""

    live_states = []

    img = None 

    def get_weights(self,vert):
        weight = 0
        for group in vert.groups:
            if group.group == self.vertex_grp_id:
                weight = group.weight
        return weight

    def to_rgb(self,c):
        rgb = round(c * 255.0)
        return rgb#(rgb,rgb,rgb)

    def pixel_loop(self,xy):
        # x= horizontal direction, y= verticall direction
        x,y =xy

        x_loop = (0,x,x,0,0,0)
        y_loop = (0,0,y,y,0,0)

        return x_loop,y_loop

    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self,context):
        layout = self.layout
        grp = context.scene.proximity_objects[self.grp]
        if grp.mode == "Proximity_obj":
            layout.prop(self,'bakeMethod')
            layout.label(text="For best results, use 'Closest', texture interpolation")
        if self.bakeMethod == "Image Sequence":
            layout.prop(self,'temporal_smooth')

        layout.prop(self,'vertex_grp')
        

    @classmethod
    def poll(self,context):
        not_edit = False if context.active_object and context.active_object.mode == 'EDIT' else True

        return pillow_check and not_edit

    def execute(self,context):
        grp = context.scene.proximity_objects[self.grp]

        if self.vertex_grp not in grp.keys():
            self.report({'ERROR'},"The group %s hasn't been assigned" % self.vertex_grp)
            return {'CANCELLED'}

        self.vert_grp_name = grp[self.vertex_grp]
        context.scene.frame_current = context.scene.frame_start
        self.rounds = 0
        self.filter_grp = grp.vertex_group_filter

        #Proximity OBJECT
        if grp.mode == "Proximity_obj":
            self.collection = grp.collection
            self.obj = grp.object   

            for obj in grp.collection.objects:
                if obj.type != 'MESH':
                    continue

                if 'ProximityBake' not in obj.data.uv_layers:
                    obj.data.uv_layers.new(name ='ProximityBake',do_init=True)

                if self.vert_grp_name not in obj.vertex_groups.keys():
                    message = "The object {0} does not contain Vertex Goup {1}"
                    self.report({'ERROR'},message.format(obj.name,self.vert_grp_name))

                    return {'CANCELLED'}

        else:#Proximity VERTEX
            self.obj = grp.object   

            if self.obj.type != 'MESH':
                self.report({'ERROR'},"Object isn't Mesh type")
                return {'CANCELLED'}
                

            if self.vert_grp_name not in self.obj.vertex_groups.keys():
                self.report({'ERROR'},"The object does not contain Vertex Goup %s" % self.vert_grp_name)
                return {'CANCELLED'}

            if 'ProximityBake' not in self.obj.data.uv_layers:
                self.obj.data.uv_layers.new(name='ProximityBake',do_init=True)
        
            self.vertex_grp_id = self.obj.vertex_groups[self.vert_grp_name].index

            if self.filter_grp:
                self.filter_id = self.obj.vertex_groups[self.filter_grp].index
        
       
        self.live_states.clear()
        #disable Live for all other groups
        for index,g in enumerate(context.scene.proximity_objects):
            if g != grp:
                self.live_states.append((index,g.live))
                g.live = False
            else:
                grp.live = True

        self.mode = grp.mode

        dir = os.path.join(bpy.path.abspath(context.scene.proximity_output), grp.object.name + "_" + grp.mode)
        if not os.path.isdir(dir):
            os.makedirs(dir)

        self.directory = dir

        wm = bpy.context.window_manager

        self.timer = wm.event_timer_add(time_step = 0.01, window=context.window)
        wm.modal_handler_add(self) 
        
        return {'RUNNING_MODAL'}

    def restore_live_states(self,context):
        for i,state in self.live_states:
            context.scene.proximity_objects[i].live = state

    def modal(self,context,event):
        f = context.scene.frame_current

        if event.type == 'TIMER':
            context.area.tag_redraw()

        if event.type in {'ESC'}:
            self.restore_live_states(context)
            #if self.mode != "Proximity_obj":
            self.shrink_uvs(context)

            if self.img:
                del self.img

            wm = bpy.context.window_manager
            wm.event_timer_remove(self.timer)
            self.report({'INFO'},"Bake Cancelled")
            return {'CANCELLED'}

        elif f > context.scene.frame_end:
            self.restore_live_states(context)
            self.shrink_uvs(context)

            if self.img:
                del self.img

            context.scene.proximity_objects[self.grp].live = False
            wm = bpy.context.window_manager
            wm.event_timer_remove(self.timer)
            self.report({'INFO'},'Images saved')
            return {'FINISHED'}

        elif is_ready[0]:
            is_ready[0] = False
            if self.mode == "Proximity_obj":
                if self.bakeMethod == 'Image Sequence':
                    self.bake_object_image_sq(context)
                else:
                    self.bake_object_pixel_sq(context)

            else:
                self.bake_verts_image_sq(context)

        return {'RUNNING_MODAL'}

    def bake_object_image_sq(self,context):
        count_x = 1
        count_y = 1
        step = 2
        self.rounds +=1
        
        size = int(sqrt(len(self.collection.objects)))*step + step
        img = Image.new('L',(size,size))

        px_direction = (-1,-1)
        px_loop_x,px_loop_y = self.pixel_loop(xy=px_direction)

        #1 iterate objects
        for obj in self.collection.objects:

            if obj.type != 'MESH':
                    continue
                
            self.vertex_grp_id = obj.vertex_groups[self.vert_grp_name].index

            if self.filter_grp:
                self.filter_id = obj.vertex_groups[self.filter_grp].index

            uv_data = obj.data.uv_layers['ProximityBake']

            #2 iterate polygons
            for poly in obj.data.polygons:
                
                x_offset = (0,1,1,0,0)
                y_offset = (0,0,1,1,0)

                #3 iterate loops
                for i,loop_i in enumerate(poly.loop_indices):
                    if self.rounds == 1:#UVs
                        if count_x > + size-step:
                            count_x = 1
                            count_y += step

                        x = count_x + x_offset[min(i,4)] 
                        y = count_y - y_offset[min(i,4)] 

                        norm_x = x/size
                        norm_y = y/size

                        uv = (norm_x,norm_y)

                        uv_data.data[loop_i].uv = uv
                    else:
                        uv = uv_data.data[loop_i].uv

                    vert_id = poly.vertices[i]

                    vert = obj.data.vertices[vert_id]

                    weight = self.get_weights(vert)
                    px_col = self.to_rgb(weight) 

                    for n in range(4):
                        px_co = (
                            round(uv[0]*size)+ px_loop_x[n],
                            round(uv[1]*size)+ px_loop_y[n],
                            )

                    try:
                        img.putpixel(px_co,px_col) 
                    except:
                        pass

                    if self.rounds > 1:
                        break

            count_x += step

        filename = "{0}_{1}_{2}.png"
        filename = filename.format(self.obj.name,self.vert_grp_name,str(context.scene.frame_current).zfill(4))
        dir =  self.directory
        path = os.path.join(dir,filename)

        img = img.transpose(Image.FLIP_TOP_BOTTOM)

        if self.img and self.temporal_smooth:
            img = Image.blend(self.img,img,0.5)

        img.save(path,format = 'PNG')
        context.scene.frame_current +=1

        self.img = img
        
        return {'PASSTHROUGH'}
    
    def bake_object_pixel_sq(self,context):
        count_y = 0
        self.rounds +=1
        
        size_x = context.scene.frame_end - context.scene.frame_start
        size_y = len(self.collection.objects)

        if self.rounds == 1:
            img = Image.new('L',(size_x,size_y))
        else:
            img = self.img

        #1 iterate objects
        for obj in self.collection.objects:
            if obj.type != 'MESH':
                    continue
                

            self.vertex_grp_id = obj.vertex_groups[self.vert_grp_name].index

            if self.filter_grp:
                self.filter_id = obj.vertex_groups[self.filter_grp].index

            uv_data = obj.data.uv_layers['ProximityBake']
            #2 iterate polygons
            for poly in obj.data.polygons:
                x_offset = (0,1,1,0,0)
                y_offset = (0,0,1,1,0)

                if self.rounds == 1:
                    #3 iterate loops
                    for i,loop_i in enumerate(poly.loop_indices):
                        x = x_offset[min(i,4)] 
                        y = count_y + y_offset[min(i,4)] 

                        norm_x = x/size_x
                        norm_y = y/size_y

                        uv = (norm_x,norm_y)

                        uv_data.data[loop_i].uv = uv 

                vert_id = poly.vertices[0]

                vert = obj.data.vertices[vert_id]

                weight = self.get_weights(vert)
                px_col = self.to_rgb(weight) 

                px_co = (
                    self.rounds-1,
                    count_y,
                    )

                try:
                    img.putpixel(px_co,px_col) 
                except:
                    
                    pass

            count_y += 1

        self.img = img

        

        if self.rounds == size_x:
            filename = "{0}_{1}_{2}-{3}.png"
            filename = filename.format(self.obj.name,self.vert_grp_name,context.scene.frame_start,context.scene.frame_end)
            dir =  self.directory
            path = os.path.join(dir,filename)

            img = img.transpose(Image.FLIP_TOP_BOTTOM)

            img.save(path,format = 'PNG')
        
            del img
        context.scene.frame_current +=1
        return {'PASSTHORUGH'}

    def bake_verts_image_sq(self,context):
        obj = self.obj
        step = 2
        self.rounds +=1

        uv_data = obj.data.uv_layers['ProximityBake']

        size = int(sqrt(len(uv_data.data)))*step + 4

        img = Image.new('L',(size,size))

        count_x = 1
        count_y = 1

        verts = {}
        
        #1 iterate polygons
        for poly in obj.data.polygons: 
            x_offset = (0,2,2,0,0)
            y_offset = (0,0,2,2,0)

            last = len(poly.loop_indices)-1
            #1 iterate loops
            for i,loop_i in enumerate(poly.loop_indices):
                if self.rounds ==1:
                    if count_x > + size-step:
                        count_x = 1
                        count_y += 4

                    x = count_x + x_offset[min(i,4)] 
                    y = count_y + y_offset[min(i,4)] 

                    norm_x = x/size
                    norm_y = y/size

                    uv = (norm_x,norm_y)

                    uv_data.data[loop_i].uv = uv
        
                else:
                    uv = uv_data.data[loop_i].uv


                if i == last:
                    count_x += 4
                #------------Put pixels-------------------
                vert_id = poly.vertices[i]

                #Only calc vert col once
                if vert_id not in verts:
                    vert = obj.data.vertices[vert_id]

                    included = True

                    if self.filter_grp:
                        included = False
                        for g in vert.groups:
                            if g.group == self.filter_id and g.weight > 0.01:
                                included = True
                                break

                    if not included:
                        continue 

                    weight = self.get_weights(vert)

                    if weight == 0:
                        continue

                    px_col = self.to_rgb(weight) 

                    verts[vert_id] = px_col
                else:
                    px_col = verts[vert_id]


                px_direction =(-1,-1)

                px_loop_x,px_loop_y = self.pixel_loop(xy=px_direction)

                for n in range(4):
                    px_co = (
                        round(uv[0]*size) + px_loop_x[n],
                        round(uv[1]*size) + px_loop_y[n],
                        )

                    try:
                        img.putpixel(px_co,px_col) 
                    except:
                        #print("out of range: ",px_co,px_col)
                        pass
                
        filename = "{0}_{1}_{2}.png"
        filename = filename.format(obj.name,self.vert_grp_name,str(context.scene.frame_current).zfill(4))
        dir =  self.directory
        path = os.path.join(dir,filename)

        img = img.transpose(Image.FLIP_TOP_BOTTOM)

        if self.img and self.temporal_smooth:
            img = Image.blend(self.img,img,0.5)
        
        
        self.img = img

        img.save(path,format = 'PNG')
        

        context.scene.frame_current +=1
        
        return {'PASSTHROUGH'}

    def shrink_uvs(self,context):
        def iterate_polys(obj,uv_data):
            #1 iterate polygons
            for poly in obj.data.polygons:
                if grp.mode != "Proximity_obj":
                    d1= 0.5/size_x
                    d2= 0.5/size_y
                    x_offset = (d1,-d1,-d1,d1,d1)
                    y_offset = (d2,d2,-d2,-d2,d2)

                else:
                    d1= 0.25/size_x
                    if self.bakeMethod == 'Pixel Sequence':
                        d2= 0.25/size_y
                    else:
                        d2= -0.25/size_y

                    x_offset = (d1,-d1,-d1,d1,d1)
                    y_offset = (d2,d2,-d2,-d2,d2)


                #1 iterate loops
                for i,loop_i in enumerate(poly.loop_indices):

                    x,y = uv_data.data[loop_i].uv

                    x = x + x_offset[min(i,4)] 
                    y = y + y_offset[min(i,4)]
                    

                    uv_data.data[loop_i].uv = (x ,y)


        
        grp = context.scene.proximity_objects[self.grp]

        step = 2
        
        if grp.mode == "Proximity_obj":
            print(grp.mode,self.bakeMethod)
            if self.bakeMethod == 'Pixel Sequence':
                size_x = context.scene.frame_end - context.scene.frame_start 
                size_y = len(self.collection.objects)
            else:
                size_x = int(sqrt(len(self.collection.objects)))*step + step
                size_y = size_x

            for obj in self.collection.objects:
                if obj.type != 'MESH':
                    continue
                uv_data = obj.data.uv_layers['ProximityBake']
                iterate_polys(obj,uv_data)
        else:
            print(grp.mode,self.bakeMethod)
            obj = self.obj
            uv_data = obj.data.uv_layers['ProximityBake']
            size_x = int(sqrt(len(uv_data.data)))*step + 4
            size_y = size_x

            iterate_polys(obj,uv_data)

        


class PROXIMITY_PT_BakePanel(Panel):
    bl_label = "Bake Settings"
    bl_idname = "PROXIMITY_PT_bakepanel"
    bl_space_type =  'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Proximity"

    def draw(self, context):
        layout = self.layout
        if not pillow_check:
            layout.alert = True
            layout.label(text="Python Pillow library required")
        else:
            layout.alert = False
            try:
                
                message = "Pillow version: " + PIL.__version__ + " ,successfully installed"
            except:
                message = ""

            layout.label(text= message)
            global additional_message
            if additional_message:
                layout.alert = True
                layout.label(text= additional_message)
                layout.alert = False
                

        if not pillow_check:
            layout.operator("proximity.install_pillow",text ='Install')
        else:
            layout.prop(context.scene,'proximity_output')


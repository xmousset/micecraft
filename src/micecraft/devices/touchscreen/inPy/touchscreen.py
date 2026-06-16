import pygame
import serial
import os
from time import sleep
from enum import Enum
import traceback
import math


# touch screen by Fabrice de Chaumont

class TouchScreen:

    class Mode(Enum):
        NORMAL = 1
        MOUSE = 2
        RAT = 3
    
    def __init__( self, nbCols = 3, nbRows = 1 , w=1024, h=600 ):
        
        print("Starting TouchScreen")
        
        print("Starting serial...")
        self.ser = serial.Serial("/dev/ttyS0",baudrate=115200, write_timeout=2, timeout=0) #115200
        #,parity=serial.PARITY_ODD,stopbits = serial.STOPBITS_TWO,bytesize= serial.SEVENBITS
        
        print( self.ser.name )
        self.send("Starting touchscreen...")
    
        self.lastError = ""
    
        pygame.init()
                
        self.gameDisplay = pygame.display.set_mode((0,0),pygame.FULLSCREEN ) # pygame.FULLSCREEN
        #self.gameDisplay = pygame.display.set_mode((0,0) ) #,pygame.FULLSCREEN ) # pygame.FULLSCREEN
        pygame.display.set_caption('LMT-Block Touchscreen')
        
        self.transparency = 255
        
        self.display_width = self.gameDisplay.get_width()
        self.display_height = self.gameDisplay.get_height()
        
        print( self.display_width )
        self.yOffset = 0
        self.bg: tuple[int, int, float] | None = None
        """None for black background, otherwise a tuple of
        (white_height, black_height, angle) in pixels and degrees for
        background with stripes."""
        self.screen_diag = 1 + int(
            math.hypot(self.display_width, self.display_height)
        )
        
        self.mode = self.Mode.NORMAL
        self.inputBuffer = ""
        
        # 
        # screen = pygame.display.set_mode(size, pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        
        
        self.black = (0,0,0)
        self.white = (255,255,255)
        
        self.clock = pygame.time.Clock()

        self.imageSize = int( self.display_width / 3.5 )
        self.nbCols = nbCols
        self.nbRows = nbRows
        self.currentImages = {} # for images using the matrix format
        self.currentXYImages = {} # for independent images. Key is the name of the image
        self.currentStripesImages: dict[str, tuple[pygame.Surface, int, int]] = {} # for stripes images.
        
        
        
        
        
        #self.img02 = self.loadImage( "cheese.png" )
        #self.img03 = self.loadImage( "plane.png" )
        #self.img04 = self.loadImage( "flower.jpg" )
        self.images = []
        self.fingers = {}
        

        self.running = True
        self.send("Touchscreen started")
    
    def setShowCalibration( self, enabled ):
        self.showCalibration = enabled
        
    def loadImage( self, file ):
        img = pygame.image.load( file )
        img = pygame.transform.scale(img,( self.imageSize,self.imageSize ))
        #imgEnhencer = ImageEnhance.Brightness( img )
        #img = imgEnhancer( 0.5 )
        #img = img.convert()
        img = img.convert_alpha()
                
        img.fill( ( 255,255,255, self.transparency) , special_flags = pygame.BLEND_RGBA_MULT)
        return img
    
    def loadImages( self, files ):
        self.files = files
        self.reloadImages()
        
    def reloadImages(self ):
        self.images = {}
        i=0
        for file in self.files:            
            self.images[i] = ( self.loadImage( file ) , file )
            i+=1
            
    def getImage( self, index ):
        image = None
        try:
            image = self.images[index][0]
        except:
            self.sendErrorFeedBack(f"getImage: Image key error:{index}" )
            image = self.images[0][0] # default image
        return image

    def getImageName( self, index ):
        return self.images[index][1]

    def createStripesImage(
        self,
        white_height: int,
        black_height: int,
        angle: float
    ) -> pygame.Surface:

        stripe_height = max(0, int(white_height)) + max(0, int(black_height))
        if stripe_height <= 0:
            return pygame.Surface((self.imageSize, self.imageSize), flags=pygame.SRCALPHA)

        img_diag = int(math.ceil(math.hypot(self.imageSize, self.imageSize))) + stripe_height
        surf = pygame.Surface((img_diag, img_diag), flags=pygame.SRCALPHA)

        white_h = max(0, int(white_height))
        black_h = max(0, int(black_height))
        for y in range(0, img_diag, stripe_height):
            if white_h > 0:
                pygame.draw.rect(surf, self.white, (0, y, img_diag, white_h))
            if black_h > 0:
                pygame.draw.rect(surf, self.black, (0, y + white_h, img_diag, black_h))

        rotated = pygame.transform.rotate(surf, angle % 180)

        rx = rotated.get_width() // 2 - self.imageSize // 2
        ry = rotated.get_height() // 2 - self.imageSize // 2
        crop_rect = pygame.Rect(rx, ry, self.imageSize, self.imageSize)
        crop_rect.clamp_ip(rotated.get_rect())
        final = rotated.subsurface(crop_rect).copy()
        return final

    def showImage( self, imageIndex , x , y ):
        x = int( self.getXCenter(x) - self.imageSize/2 )
        y = int ( self.getYCenter(y) -self.imageSize/2 )
        self.gameDisplay.blit( self.getImage(imageIndex), (x,y))
    
    def showXYImage( self, name ):
        image = self.currentXYImages[name]
        imageIndex = image[0]
        x = image[1]
        y = image[2]
        r = image[3]
        s = image[4]
        
        
        size = self.imageSize*s
        
        # center image
        #x = int ( x - size/2 )
        #y = int ( y - size/2 )
        
        
        
        i2 = pygame.transform.rotozoom( self.getImage(imageIndex) , r , s )
        
        x = int ( x - i2.get_width()/2 )
        y = int ( y - i2.get_height()/2 )
        
        self.gameDisplay.blit( i2, (x,y) )
    
    def showXYStripesImage( self, name: str ):
        surf, x, y = self.currentStripesImages[name]
        
        x = x - surf.get_width()//2
        y = y - surf.get_height()//2
        self.gameDisplay.blit( surf, (x,y) )
    
    def setImage( self, imageIndex, x, y=1 ):
        self.currentImages[(x,y)] = imageIndex
        
    def removeImage( self, x,y=1 ):
        if ( ( x , y ) ) in self.currentImages:
            self.currentImages.pop( ( x,y ) )
    
    def setXYImage( self, name, index, x, y, r, s ):
        self.currentXYImages[name] = [ index, x, y, r , s ]

    def removeXYImage( self, name ):
        if name in self.currentXYImages:
            self.currentXYImages.pop( name )
    
    def setXYStripesImage(
        self,
        name: str,
        white_height: int,
        black_height: int,
        angle: float,
        x: int,
        y: int,
    ):
        surf = self.createStripesImage( white_height, black_height, angle )
        self.currentStripesImages[name] = (surf, x, y )
    
    def removeXYStripesImage( self, name:str ):
        if name in self.currentStripesImages:
            self.currentStripesImages.pop( name )

    def removeAllImages( self ):
        self.currentImages={}
        self.currentXYImages = {}
        self.currentStripesImages = {}
    
    def getXCenter( self, x ):
        w = self.display_width/self.nbCols
        return int( (x-1)*(w) + w/2 )

    def getYCenter( self, y ):
        h = self.display_height/self.nbRows
        return int( (y-1)*(h) + h/2 + self.yOffset )
    
    
    def drawCalibration( self ):
        for x in range( 1, self.nbCols+1 ):            
            x = self.getXCenter( x )
            pygame.draw.line( self.gameDisplay, (255,0,0), (x,0), (x,self.display_height), 5)
        for y in range( 1, self.nbRows+1 ):
            y = self.getYCenter( y )
            pygame.draw.line( self.gameDisplay, (255,0,0), (0,y), (self.display_width,y), 5)

    def setBgStripes(self, white_height: int, black_height: int, angle: float):
        """Configure full-screen white/black stripe pattern.
        
        Parameters:
        -----------
        white_height: int - height of white stripes in pixels (0 for no white stripes)
        black_height: int - height of black stripes in pixels (0 for no black stripes)
        angle: float - rotation angle of stripes in degrees (-90 to 90)
        
        Example usage:
        --------------
        ts.setStripes(white_height=20, black_height=20, angle=45)
        
        This would create a pattern of 20px white stripes alternating with
        20px black stripes, rotated 45 degrees.
        """
        
        self.bg = (
            max(0, white_height),
            max(0, black_height),
            angle % 180
        )
    
    def removeBg(self):
        """Remove any stripe pattern and return to normal display."""
        self.bg = None

    def _draw_bg(self):
        """Draw alternating white/black stripes filling the screen, rotated by angle."""
        if self.bg is None:
            self.gameDisplay.fill(self.black)
            return

        surf = pygame.Surface((self.screen_diag, self.screen_diag), flags=pygame.SRCALPHA)

        stripe_height = self.bg[0] + self.bg[1]
        if stripe_height <= 0:
            self.gameDisplay.fill(self.black)
            return
        
        for i in range(0, self.screen_diag, stripe_height):
            if self.bg[0] > 0:
                pygame.draw.rect(
                    surf,
                    self.white,
                    (0, i, self.screen_diag, self.bg[0])
                )
            if self.bg[1] > 0:
                pygame.draw.rect(
                    surf,
                    self.black,
                    (0, i + self.bg[0], self.screen_diag, self.bg[1])
                )

        rotated = pygame.transform.rotate(surf, self.bg[2])
        rx = int(self.display_width / 2 - rotated.get_width() / 2)
        ry = int(self.display_height / 2 - rotated.get_height() / 2)
        self.gameDisplay.blit(rotated, (rx, ry))
    
    def fingerDown( self, xf, yf ):
        # test if the symbol is touched
        
        touched = False
        
        for name in self.currentXYImages:
            image = self.currentXYImages[name]
            imageIndex = image[0]
            x = image[1]
            y = image[2]
            r = image[3]
            s = image[4]        
            size = self.imageSize*s
            print( "xy test touch" , size , x,y , xf, yf )
            dist = math.dist( (x,y), (xf,yf) )
            print( "dist: ", dist, dist < size/2 )
            if dist < size/2:
                self.send(f"symbol xy touched {name} id {imageIndex} at {x},{y},{int(xf)},{int(yf)}")
                touched = True
            
            
        for coord,imageIndex in self.currentImages.items():
            x = coord[0]
            y = coord[1]
            x1 = int( self.getXCenter(x) - self.imageSize/2 )
            y1 = int ( self.getYCenter(y) -self.imageSize/2 )
            x2 = x1 + self.imageSize
            y2 = y1 + self.imageSize
            if xf > x1 and xf < x2 and yf > y1 and yf < y2:
                # touched
                self.send(f"symbol touched id {imageIndex} at {x},{y},{int(xf)},{int(yf)}")
                touched = True
        
        if not touched:        
            self.send(f"missed {int(xf)},{int(yf)}")
    
    def send( self, message ):
        message+= "\n"
        message = message.encode("utf-8")
        self.ser.write( message )
    
    def processCommands( self ):
        
        dataIn = self.ser.readline()        
        
        try:
            dataIn = dataIn.decode("utf_8")
        except:
            #error in decode
            self.sendErrorFeedBack("Can't uf8-decode command")
            return
        
        self.inputBuffer += dataIn
        #print( f"input buffer: {self.inputBuffer}")
        
        command = None
        
        buffer = self.inputBuffer

        if "\n" in buffer:
            splits = buffer.split("\n")
            command = splits[0]
            
            loc = buffer.index("\n")
            
            '''
            print("---" )
            print( f"slash n location: {loc} ")
            print( f"Input buffer : {self.inputBuffer}" )
            print( f"Splits : {splits}")
            print( f"Command : {command}")
            '''
            
            self.inputBuffer = self.inputBuffer[ len(command)+1 : ]


        '''
        if "\n" in self.inputBuffer:
            splits = self.inputBuffer.split("\n")
            command = splits[0]
            
            loc = self.inputBuffer.index("\n")
            print("---" )
            print( f"slash n location: {loc} ")
            print( f"Input buffer : {self.inputBuffer}" )
            print( f"Splits : {splits}")
            print( f"Command : {command}")
            
            self.inputBuffer = self.inputBuffer[ len(command)+1 : ]
        '''
            
            
     
        
        if command != None:
            if len( command ) > 0:
                print( f"process command : {command}" )
                
                c = command.split(" ")
                
                if "hello" in c[0]:
                    self.send("Touchscreen - driver v2.2")
                
                if "setImage" in c[0]:
                    #setImage 0 1 1
                    #print( "current command:" + command )
                    
                    
                    imageIndex = int(c[1])
                    x = int(c[2])
                    y = int(c[3])
                    self.setImage( imageIndex , x, y )                    
                    
                if "setXYImage" in c[0]:
                    
                    print(f"setXYcommand: {command}")
                    
                    name = c[1]
                    imageIndex = int(c[2])
                    x = float(c[3])
                    y = float(c[4])
                    r = float(c[5])
                    s = float(c[6])                    
                    self.setXYImage( name, imageIndex, x, y, r , s )
                
                if "removeXYImage" in c[0]:
                    name = c[1]                    
                    ts.removeXYImage( name ) 
                    
                
                if "removeImage" in c[0]:
                    
                    x = int( c[1] )
                    y = int( c[2] )
                    ts.removeImage( x , y )
                    
                if "config" in c[0]:
                    # config col row size
                    
                    x = int( c[1] )
                    y = int( c[2] )                    
                    size = int ( c[3] )                    
                    self.nbCols = x
                    self.nbRows = y
                    self.imageSize = size
                    self.reloadImages()
                    
                if "transparency" in c[0]:
                    # from 0 to 255
                    
                    self.transparency = int( c[1] )
                    self.reloadImages()
                    
                if "yOffset" in c[0]:
                    
                    self.yOffset = int( c[1] )
                
                # todo: collaspe all the mode in one variable
                if "mouseMode" in c[0]:
                    self.mode = self.Mode.MOUSE
                
                if "ratMode" in c[0]:
                    self.mode = self.Mode.RAT
                
                if "normalMode" in c[0]:
                    self.mode = self.Mode.NORMAL
                    
                if "ping" in c[0]:
                    
                    self.send("pong")
                    
                if "clear" in c[0]:
                    self.removeAllImages()
                    self.removeBg()
                
                if "calibration" in c[0]:
                    if "show" in command:
                        self.showCalibration = True
                    if "hide" in command:
                        self.showCalibration = False
                        
                if "crash" in c[0]:                    
                    raise Exception("Crash asked by user")
                
                if "setBgStripes" in c[0]:
                    white = int(c[1])
                    black = int(c[2])
                    angle = float(c[3])
                    self.setBgStripes(white, black, angle)
                
                if "removeBg" in c[0]:
                    self.removeBg()
                
                if "setXYStripesImage" in c[0]:
                    name = c[1]
                    white = int(c[2])
                    black = int(c[3])
                    angle = float(c[4])
                    x = int(c[5])
                    y = int(c[6])
                    self.setXYStripesImage( name, white, black, angle, x, y )
                
                if "removeXYStripesImage" in c[0]:
                    name = c[1]
                    self.removeXYStripesImage( name )
                
        return command

    def sendErrorFeedBack( self, error ):
        if self.lastError == error: # check error to avoid repeating the same one all the time
            return
        
        self.send(f"Touchscreen - error - traceback: {error}" )
        self.lastError = error
    
    def process( self ):
        
        for i in range(10):
            command = self.processCommands()
            if command == None:
                break
            
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    self.running = False
                    print("Q key hit: exit")
                if event.key == pygame.K_c:
                    self.showCalibration = not self.showCalibration
            if event.type == pygame.MOUSEBUTTONDOWN:
                print("Mouse button pressed")
                
            if event.type == pygame.FINGERDOWN:
                #self.send( f"debug area size: {self.gameDisplay.get_height()},{self.gameDisplay.get_width()}")
                #self.send( f"debug event.x,y : {event.x},{event.y}")
                
                # coordinates from 0 to 1
                xx = event.x
                yy = event.y
                
                if self.mode == self.Mode.RAT:
                    #print("rat mode")
                    
                    # in rat mode, the screen is reversed, meaning the screen is in
                    # landscape layout and the wire is getting out from the top left corner when
                    # the user watch the screen.
                    ratioY = 0.32 # the ratio of the y part of the screen to be used.
                    yy = ( ( 1-event.y ) - ratioY ) * ( 1/(1-ratioY) )
                    xx = 1-event.x
                    
                if self.mode == self.Mode.MOUSE:
                    # rotate
                    
                    #yy = (1-(event.x+0.5))*2 # translate up
                    
                    # transform
                    
                    '''
                    # bottom of the screen
                    yy = (1-(event.x+0.6))*2.5
                    xx = event.y*1.05
                    '''
                    yy = (1-(event.x+0.25))*2.5
                    xx = event.y*1.05
                    
                    
                    '''
                    xx = (1-(xx+0.5))*2 # translate up
                    xxx = yy
                    yyy = xx
                    xx = xxx
                    yy = yyy
                    '''
                
                x = xx * self.gameDisplay.get_width()
                y = yy * self.gameDisplay.get_height()
                
                self.fingers[event.finger_id] = x, y
                print( "finger down" , event.finger_id, x , y )
                self.fingerDown( x , y )
                
                
                
            if event.type == pygame.FINGERUP:
                self.fingers.pop(event.finger_id, None)
                print( "finger up" , event.finger_id )

        self._draw_bg()
        
        for coord,imageIndex in self.currentImages.items():
            x = coord[0]
            y = coord[1]            
            self.showImage( imageIndex, x, y )
        
        for image in self.currentXYImages:
            self.showXYImage( image )
        
        for name in self.currentStripesImages:
            self.showXYStripesImage( name )
        
        '''
        ts.showImage( 1, 2, 1 )
        ts.showImage( 2, 3, 1 )
        '''
        
        
        if self.showCalibration:
            self.drawCalibration()
               
            for finger in self.fingers:
                xf, yf = self.fingers[finger]
                pygame.draw.line( self.gameDisplay, (0,255,0), (xf-50,yf-50), (xf+50,yf+50), 5)
                pygame.draw.line( self.gameDisplay, (0,255,0), (xf+50,yf-50), (xf-50,yf+50), 5)
        
            
        pygame.display.update()
        self.clock.tick(30)

        
if __name__ == '__main__':
    
    
    
    print("Starting touchscreen inner example...")
    
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)
    
    '''
    #ser = serial.Serial("/dev/ttyS0",baudrate=9600, writeTimeout=2, timeout=10 ,parity=serial.PARITY_NONE, stopbits = serial.STOPBITS_ONE, bytesize = serial.EIGHTBITS )
    ser = serial.Serial("/dev/ttyS0",baudrate=115200, writeTimeout=2, timeout=10 )
    print( ser.name )
    #while True :
    
    i=0
    while True:
        ser.flush()
        i+=1
        print( i, "flushin")
        #c=c+"echo\n"
        try:
            ser.write( "hello heloow\n".encode("utf_8" ) )
            print("writeok")
        except:
            print("timeout")
    ser.close()
    quit()
    '''
    ts = TouchScreen( 3,1 )
    ts.loadImages( ["plane.jpg" , "flower.jpg", "bomb.jpg","spider.jpg","001.jpg","003.jpg","004.jpg","005.jpg","006.jpg","007.jpg","008.jpg","009.jpg","bug.png"] )
    ts.setShowCalibration( True )
    
    
    ts.setImage( 0 , 1, 1 )
    ts.setImage( 1 , 2, 1 )
    ts.setImage( 2 , 3, 1 )
    
    #ts.setXYImage( "testXYImage", 12, 1920/2,1080/2,45,0.5 )
    
    #ts.removeImage( 1 , 1 )
    
    
    while ts.running:
        
        try:
            ts.process()
        except Exception as e:
            
            error = traceback.format_exc()
            print( error )
            ts.running = False
        
        '''
        try:
            ts.process()
        except Exception as e:
            
            error = traceback.format_exc()
            error = error.replace("\n","*")
            ts.sendErrorFeedBack( f"{error}" )
        '''
            
        sleep( 0.001 )

        
    pygame.quit()
    print("Quit")
    quit()
    
'''



# package needed:



display_width = 1024
display_height = 768

gameDisplay = pygame.display.set_mode((display_width,display_height))
pygame.display.set_caption('LMT-Block Touchscreen')

black = (0,0,0)
white = (255,255,255)

clock = pygame.time.Clock()

imageSize = 200
nbColomn = 4

def loadImage( file ):
    img = pygame.image.load( file )
    img = pygame.transform.scale(img,( imageSize,imageSize ))
    img = img.convert()
    return img


def showImage( image , position ):
    x = int( display_width/nbColomn - imageSize/2 )
    y = int ( display_height/2-imageSize/2 )
    gameDisplay.blit( image, (x,y))
    

img02 = loadImage( "cheese.png" )
img03 = loadImage( "plane.png" )
img04 = loadImage( "flower.jpg" )


running = True


x = (display_width * 0.45)
y = (display_height * 0.8)

# main loop
while running:

    # manage events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    gameDisplay.fill(black)
    gameDisplay.blit(img02, (x+100,y))
    gameDisplay.blit(img03, (x-100,y))
    gameDisplay.blit(img04, (x+200,y))
    y-=1
    
    showImage( img02, 1 )
    
        
    pygame.display.update()
    clock.tick(60) # 60 image per second
    #print( y, clock.get_fps())


pygame.quit()
quit()

'''

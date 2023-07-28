

import ccxt
from flask import Flask, request, abort
from threading import Timer
import time
import json
import logging
#import csv

verbose = False
_ORDER_TIMEOUT_ = 40

from datetime import datetime
# today = datetime.today()
# year = today.year
# month = today.month
# day = today.day
#print("Current year:", today.year)
#print("Current month:", today.month)
#print("Current day:", today.day)
#print("Hour =", today.hour)
#print("Minute =", today.minute)
#print("Second =", today.second )

def dateString():
    return datetime.today().strftime("%Y/%m/%d")

def timeNow():
    return time.strftime("%H:%M:%S")

# create logger for trades
logger = logging.getLogger('webhook')
fh = logging.FileHandler('webhook.log')
logger.addHandler( fh )
logger.level = logging.INFO

def floor( number ):
    return number // 1

def ceil( number ):
    return int(-(-number // 1))

def roundUpTick( value, tick )-> float:
    return ceil( value / tick ) * tick

def roundDownTick( value, tick )-> float:
    return floor( value / tick ) * tick

def roundToTick( value, tick )-> float:
    return round( value / tick ) * tick

def printf(*args, sep=" ", **kwargs):
    logger.info( dateString()+sep.join(map(str,args)), **kwargs)
    print( ""+sep.join(map(str,args)), **kwargs)

class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)

class position_c:
    def __init__(self, symbol, position) -> None:
        self.symbol = symbol
        self.position = position
    def getKey(cls, key):
        return cls.position.get(key)

class order_c:
    def __init__(self, symbol = "", type = "", quantity = 0.0, leverage = 1, delay = 0, reverse = False) -> None:
        self.type = type
        self.symbol = symbol
        self.quantity = quantity
        self.leverage = leverage
        self.reduced = False
        self.id = ""
        self.delay = delay
        self.reverse = reverse
        self.timestamp = time.monotonic()
    def setType(cls, type):
        cls.type = type
    def setSymbol(cls, symbol):
        cls.symbol = symbol
    def setLeverage(cls, leverage):
        cls.leverage = int(leverage)
    def setQuantity(cls, quantity):
        cls.quantity = int(quantity)
    def timedOut(cls):
        return ( cls.timestamp + _ORDER_TIMEOUT_ < time.monotonic() )
    def delayed(cls):
        return (cls.timestamp + cls.delay > time.monotonic() )

class account_c:
    def __init__(self, exchange = None, name = 'default', apiKey = None, secret = None, password = None )->None:
        if( name.isnumeric() ):
            printf( " * FATAL ERROR: Account 'id' can not be only  numeric" )
            raise SystemExit()
        
        self.accountName = name
        self.canFlipPosition = False
        self.positionslist = []
        self.ordersQueue = []
        self.activeOrders = []
        self.symbolStatus = {}
        if( exchange == None ):
            printf( " * FATAL ERROR: No exchange was resquested" )
            raise SystemExit()
        
        if( exchange.lower() == 'kucoinfutures' ):
            self.exchange = ccxt.kucoinfutures( {
                'apiKey': apiKey,
                'secret': secret,
                'password': password,
                #'enableRateLimit': True
                } )
                #self.exchange.rateLimit = 333
        elif( exchange.lower() == 'bitget' ):
            self.exchange = ccxt.bitget({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.canFlipPosition = True
            # self.exchange.set_sandbox_mode( True )
            #print( self.exchange.set_position_mode( False ) )
        elif( exchange.lower() == 'bingx' ):
            self.exchange = ccxt.bingx({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'coinex' ):
            self.exchange = ccxt.coinex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.canFlipPosition = False
        elif( exchange.lower() == 'mexc' ):
            self.exchange = ccxt.mexc({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'phemex' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'phemexdemo' ):
            self.exchange = ccxt.phemex({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
        elif( exchange.lower() == 'bybit' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
        elif( exchange.lower() == 'bybitdemo' ):
            self.exchange = ccxt.bybit({
                "apiKey": apiKey,
                "secret": secret,
                'password': password,
                "options": {'defaultType': 'swap', 'adjustForTimeDifference' : True},
                #"timeout": 60000,
                "enableRateLimit": True
                })
            self.exchange.set_sandbox_mode( True )
        else:
            printf( " * FATAL ERROR: Unsupported exchange:", exchange )
            raise SystemExit()

        if( self.exchange == None ):
            printf( " * FATAL ERROR: Exchange creation failed" )
            raise SystemExit()
        
        # Some exchanges don't have all fields properly filled, but we can find out
        # the values in another field. Instead of adding exceptions at each other function
        # let's reconstruct the markets dictionary trying to fix those values
        self.markets = {}
        markets = self.exchange.load_markets()
        marketKeys = markets.keys()
        for key in marketKeys:
            if( not key.endswith(':USDT') ):  # skip not USDT pairs. All the code is based on USDT
                continue

            thisMarket = markets[key]
            if( thisMarket.get('settle') != 'USDT' ): # double check
                continue

            if( thisMarket.get('contractSize') == None ):
                # in Phemex we can extract the contractSize from the description.
                # it's always going to be 1, but let's handle it in case they change it
                if( self.exchange.id == 'phemex' ):
                    description = thisMarket['info'].get('description')
                    s = description[ description.find('Each contract is worth') + len('Each contract is worth ') : ]
                    list = s.split( ' ', 1 )
                    thisMarket['contractSize'] = float( list[0] )
                    #print( "MARKET FIX ContractSize", thisMarket['contractSize'], type(thisMarket.get('contractSize')) )
                else:
                    print( "WARNING: Market", self.exchange.id, "doesn't have contractSize" )

            # make sure the market has a precision value
            try:
                precision = thisMarket['precision'].get('amount')
            except Exception as e:
                print( " * FATAL ERROR: Market", self.exchange.id, "doesn't have precision value" )
                SystemError()

            # some exchanges don't have a minimum purchase amount defined
            try:
                minAmount = thisMarket['limits']['amount'].get('min')
            except Exception as e:
                minAmount = None
                l = thisMarket.get('limits')
                if( l != None ):
                    a = l.get('amount')
                    if( a != None ):
                        minAmount = a.get('min')

            if( minAmount == None ): # replace minimum amount with precision value
                thisMarket['limits']['amount']['min'] = float(precision)
                #print( "MARKET FIX minimum AMOUT", thisMarket['limits']['amount']['min'], type(thisMarket['limits']['amount']['min']) )

            # Store the market into the local markets dictionary
            self.markets[key] = thisMarket

            # also generate an empty list of the USDT symbols to keep track of marginMode and Leverage status
            self.symbolStatus[key] = { 'marginMode': '', 'leverage': 0 }


        self.balance = self.fetchBalance()
        print( self.balance )


        '''
        if( self.exchange.id == 'bybit' ):
            print( 'has setPositionMode', self.exchange.has.get('setPositionMode') )
            #tradeMode integer required
            #Possible values: [0, 1] 0=crossMargin, 1=isolatedMargin
            # buyLeverage, sellLeverage string required
            # params = { 'category':'linear', 'tradeMode':1, 'buyLeverage':'3', 'sellLeverage':'3' }
            try:
                print( 'setPositionMode', self.exchange.set_position_mode( False, "ATOM/USDT:USDT" ) )
            except Exception as e:
                print(e)

            # isolated or cross
            try:
                print( self.exchange.set_margin_mode( 'cross', 'ATOM/USDT:USDT', {'leverage':4} ) )
            except Exception as e:
                print(e)

            print( 'has setLeverage', self.exchange.has.get('setLeverage') )
            #params = {'category':'linear'}
            params = {}
            try:
                print( 'setLeverage', self.exchange.set_leverage( 8, "ATOM/USDT:USDT", params=params ) )
            except Exception as e:
                print(e)
            
        if( self.exchange.id == 'phemex' ):
            print( 'has setPositionMode', self.exchange.has.get('setPositionMode') )
            print( 'setPositionMode', self.exchange.set_position_mode( False, "ATOM/USDT:USDT" ) )
            print( 'has setLeverage', self.exchange.has.get('setLeverage') )
            print( 'setLeverage', self.exchange.set_leverage( 13, "ATOM/USDT:USDT" ) )

        if( self.exchange.id == 'mexc' ):
            print( self.exchange.has.get('fetchPositionMode') )
            print( self.exchange.fetch_position_mode("ATOM/USDT:USDT") )
            # (params, 'openType')  # 1 or 2 -  1: isolated position, 2: full position
            # (params, 'positionType')  # 1 or 2 - 1: Long 2: short
            print( self.exchange.has.get('setLeverage') )
            print( self.exchange.set_leverage( 4, "ATOM/USDT:USDT", params = { 'openType': 1, 'positionType': 1} ) )
            print( self.exchange.set_leverage( 4, "ATOM/USDT:USDT", params = { 'openType': 1, 'positionType': 2} ) )
            print( self.exchange.has.get('setPositionMode') )
            print( self.exchange.set_position_mode( False, "ATOM/USDT:USDT" ) )
        
        if( self.exchange.id == 'bingx' ):
            atomMarket = self.markets.get( "ATOM/USDT:USDT" )
            print( atomMarket )

            # set margin mode to 'cross' or 'isolated'
            print( self.exchange.set_margin_mode( 'cross', 'ATOM/USDT:USDT' ) )
            print( self.exchange.set_leverage( 10, 'ATOM/USDT:USDT', params = {'side':'LONG'} ) )
            print( self.exchange.set_leverage( 10, 'ATOM/USDT:USDT', params = {'side':'SHORT'} ) )
            
        if( self.exchange.id == 'bitget' ):
            # margin modes: 'fixed' 'crossed'
            # in bitget they call 'fixed' to 'isolated' margin
            print( self.exchange.set_margin_mode( 'fixed', 'ATOM/USDT:USDT' ) )
            print( self.exchange.set_leverage( 3, 'ATOM/USDT:USDT' ) )

        if( self.exchange.id == 'coinex' ):
            # margin mode uses the names: 'isolated' and 'cross'
            # it could also be set in the params with the key 'position_type'
            # position_type	(Integer)	1 Isolated Margin 2 Cross Margin
            
            #print( self.exchange.set_margin_mode( 'isolated', 'ATOM/USDT:USDT', params = {'leverage':3, 'position_type':1} ) )

            # Coinex doesn't addept any number as leverage. It must be on the list.
            atomMarket = self.markets.get( "ATOM/USDT:USDT" )
            validLeverages = list(map(int, atomMarket['info']['leverages']))
            targetLeverage = 17
            leverage = 1
            for l in validLeverages:
                if( l > targetLeverage ):
                    break
                leverage = l
            
            print( self.exchange.set_margin_mode( 'isolated', 'ATOM/USDT:USDT', params = {'leverage':leverage} ) )
        '''

        self.refreshPositions(True)

    ## methods ##

    def print(cls, *args, sep=" ", **kwargs): # adds account and exchange information to the message
        logger.info( dateString() +'['+ cls.accountName +'/'+ cls.exchange.id +'] '+sep.join(map(str,args)), **kwargs)
        print( '['+ cls.accountName +'/'+ cls.exchange.id +'] '+sep.join(map(str,args)), **kwargs)

    def verifyLeverageRange( cls, symbol, leverage )->int:

        leverage = max( leverage, 1 )
        maxLeverage = cls.findMaxLeverageForSymbol( symbol )
        
        if( maxLeverage != None and maxLeverage < leverage ):
            cls.print( " * WARNING: Leverage out of bounds. Readjusting to", str(maxLeverage)+"x" )
            leverage = maxLeverage

        # coinex has a list of valid leverage values
        if( cls.exchange.id != 'coinex' ):
            return leverage
        
        thisMarket = cls.markets.get( symbol )
        validLeverages = list(map(int, thisMarket['info']['leverages']))
        safeLeverage = 1
        for value in validLeverages:
            if( value > leverage ):
                break
            safeLeverage = value
        
        return safeLeverage


    def updateSymbolLeverage( cls, symbol, leverage ):
        # also sets marginMode to isolated

        if( leverage < 1 ): #leverage 0 indicates we are closing a position
            return

        if( cls.symbolStatus[ symbol ]['marginMode'] != 'isolated' or cls.symbolStatus[ symbol ]['leverage'] != leverage ):
            if( cls.exchange.id == 'kucoinfutures' ):
                #kucoinfutured is always in isolated mode and leverage is passed as a parm. Do nothing
                cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'
                cls.symbolStatus[ symbol ]['leverage'] = leverage
            
            if( cls.exchange.id == 'bitget' ):
                # bitget also requires to set position mode (hedged or one sided)
                response = cls.exchange.set_position_mode( False, symbol )
                # margin modes: 'fixed' 'crossed'
                # in bitget they call 'fixed' to 'isolated' margin
                response = cls.exchange.set_margin_mode( 'fixed', symbol )
                if( response.get('marginMode' == 'fixed') ):
                    cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'
                response = cls.exchange.set_leverage( leverage, symbol )
                if( response.get('code') == '0' ):
                    cls.symbolStatus[ symbol ]['leverage'] = leverage

            if( cls.exchange.id == 'bingx' ):
                # set margin mode to 'cross' or 'isolated'
                response = cls.exchange.set_margin_mode( 'isolated', symbol )
                if( response.get('code') == '0' ):
                    cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'

                response = cls.exchange.set_leverage( 10, symbol, params = {'side':'LONG'} )
                response2 = cls.exchange.set_leverage( 10, symbol, params = {'side':'SHORT'} )
                if( response.get('code') == '0' and response2.get('code') == '0' ):
                    cls.symbolStatus[ symbol ]['leverage'] = leverage
                
            if( cls.exchange.id == 'coinex' ):
                # margin mode uses the names: 'isolated' and 'cross'
                # it could also be set in the params with the key 'position_type'
                # position_type	(Integer)	1 Isolated Margin 2 Cross Margin

                # Coinex doesn't accept any number as leverage. It must be on the list.
                leverage = cls.verifyLeverageRange( symbol, leverage )
                
                response = cls.exchange.set_margin_mode( 'isolated', symbol, params = {'leverage':leverage} )
                if( response.get('message') == 'OK' ):
                    cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'
                    cls.symbolStatus[ symbol ]['leverage'] = leverage

            if( cls.exchange.id == 'mexc' ):
                cls.exchange.set_position_mode( False, symbol )
                cls.exchange.set_leverage( leverage, symbol, params = {'openType': 1, 'positionType': 1} )
                cls.exchange.set_leverage( leverage, symbol, params = {'openType': 1, 'positionType': 2} )
                cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'
                cls.symbolStatus[ symbol ]['leverage'] = leverage

            if( cls.exchange.id == 'phemex' ):
                response = cls.exchange.set_position_mode( False, symbol )
                if( response.get('data') != 'ok' ):
                    cls.print( " * Warning [phemex] updateSymbolLeverage: Failed to set position mode to Swap")

                # from phemex API documentation: The sign of leverageEr indicates margin mode, i.e. leverage <= 0 means cross-margin-mode, leverage > 0 means isolated-margin-mode.
                response = cls.exchange.set_leverage( leverage, symbol )
                if( response.get('data') == 'ok' ):
                    cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'
                    cls.symbolStatus[ symbol ]['leverage'] = leverage
            
            if( cls.exchange.id == 'bybit' ):
                #tradeMode integer required
                #Possible values: [0, 1] 0=crossMargin, 1=isolatedMargin
                # buyLeverage, sellLeverage string required

                # always set position mode to oneSided
                # FIXME: we should not do this every time
                try:
                    response = cls.exchange.set_position_mode( False, symbol )
                except Exception as e:
                    for a in e.args:
                        # bybit {"retCode":140025,"retMsg":"position mode not modified","result":{},"retExtInfo":{},"time":1690530385019}
                        if '"retCode":140025' in a:
                            pass
                        else:
                            print( " * Error: updateSymbolLeverage: Unhandled Exception", a )
                
                # see if we have to change marginMode (does both) or just leverage
                if( cls.symbolStatus[ symbol ]['marginMode'] != 'isolated' ):
                    # isolated or cross
                    try:
                        response = cls.exchange.set_margin_mode( 'isolated', symbol, {'leverage':leverage} )
                        cls.symbolStatus[ symbol ]['marginMode'] = 'isolated'
                        cls.symbolStatus[ symbol ]['leverage'] = leverage
                    except Exception as e:
                        for a in e.args:
                            # bybit {"retCode":140026,"retMsg":"Isolated not modified","result":{},"retExtInfo":{},"time":1690530385642}
                            if( '"retCode":140026' in a ):
                                pass
                            else:
                                print( " * Error: updateSymbolLeverage: Unhandled Exception", a )
                else:
                    # update only leverage
                    try:
                        response = cls.exchange.set_leverage( leverage, symbol )
                        cls.symbolStatus[ symbol ]['leverage'] = leverage
                    except Exception as e:
                        for a in e.args:
                            # bybit {"retCode":140043,"retMsg":"leverage not modified","result":{},"retExtInfo":{},"time":1690530386264}
                            if( '"retCode":140043' in a ):
                                pass
                            else:
                                print( " * Error: updateSymbolLeverage: Unhandled Exception", a )
                
            if( cls.symbolStatus[ symbol ]['marginMode'] == 'isolated' and cls.symbolStatus[ symbol ]['leverage'] == leverage ):
                cls.print( "* Leverage updated: Margin Mode:", cls.symbolStatus[ symbol ]['marginMode'] + " Leverage: " + str(cls.symbolStatus[ symbol ]['leverage']) + "x" )


    def fetchBalance(cls):
        params = {}
        if( cls.exchange.id == "phemex" ):
            params = { "type":"swap", "code":"USDT" }
        
        response = cls.exchange.fetch_balance( params )

        if( cls.exchange.id == "bitget" ):
            # Bitget response message is all over the place!!
            # so we reconstruct it from the embedded exchange info
            data = response['info'][0]
            balance = {}
            balance['free'] = float( data.get('crossMaxAvailable') )
            balance['used'] = float( data.get('available') )
            balance['total'] = float( data.get('usdtEquity') )
        elif( cls.exchange.id == "coinex" ):
            # Coinex response isn't much better. We also reconstruct it
            data = response['info'].get('data')
            data = data.get('USDT')
            balance = {}
            balance['free'] = float( data.get('available') )
            balance['used'] = float( data.get('margin') )
            balance['total'] = balance['free'] + balance['used'] + float( data.get('profit_unreal') )
        else:
            balance = response.get('USDT')
        
        return balance
    
    def fetchAvailableBalance(cls)->float:
        if( cls.exchange.id == "bitget" ):
            # Bitget response message is WRONG!!
            response = cls.fetchBalance()
            return response.get( 'free' )
        
        params = {}
        if( cls.exchange.id == "phemex" ):
            params = { "type":"swap", "code":"USDT" }

        available = cls.exchange.fetch_free_balance( params )
        return available.get('USDT')
    
    def fetchBuyPrice(cls, symbol)->float:
        orderbook = cls.exchange.fetch_order_book(symbol)
        ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
        return ask

    def fetchSellPrice(cls, symbol)->float:
        orderbook = cls.exchange.fetch_order_book(symbol)
        bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
        return bid

    def fetchAveragePrice(cls, symbol)->float:
        orderbook = cls.exchange.fetch_order_book(symbol)
        bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
        ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
        return ( bid + ask ) * 0.5

    def getPositionBySymbol(cls, symbol)->position_c:
        for pos in cls.positionslist:
            if( pos.symbol == symbol ):
                return pos
        return None
    
    def findSymbolFromPairName(cls, paircmd):
        #first let's check if the pair string contains
        #a backslash. If it does it's probably already a symbol
        #but it also may not include the ':USDT' ending
        if '/' not in paircmd and paircmd.endswith('USDT'):
            paircmd = paircmd[:-4]
            paircmd += '/USDT:USDT'

        if '/' in paircmd and not paircmd.endswith(':USDT'):
            paircmd += ':USDT'

        #try the more direct approach
        m = cls.markets.get(paircmd)
        if( m != None ):
            return m.get('symbol')

        #so now let's find it in the list using the id
        for m in cls.markets:
            id = cls.markets[m]['id'] 
            symbol = cls.markets[m]['symbol']
            if( symbol == paircmd or id == paircmd ):
                return symbol
        return None
    
    def findContractSizeForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m == None ):
            cls.print( ' * ERROR: findContractSizeForSymbol called with unknown symbol:', symbol )
            return 1
        return m.get('contractSize')
    
    def findPrecisionForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m == None ):
            cls.print( ' * ERROR: findPrecisionForSymbol called with unknown symbol:', symbol )
            return 1
        return m['precision'].get('amount')
    
    def findMinimumAmountForSymbol(cls, symbol)->float:
        m = cls.markets.get(symbol)
        if( m != None ):
            return m['limits']['amount'].get('min')
        return cls.findPrecisionForSymbol( symbol )
    
    def findMaxLeverageForSymbol(cls, symbol)->float:
        #'leverage': {'min': 1.0, 'max': 50.0}}
        m = cls.markets.get(symbol)
        if( m == None ):
            cls.print( ' * ERROR: findMaxLeverageForSymbol called with unknown symbol:', symbol )
            return 0
        maxLeverage = m['limits']['leverage'].get('max')
        if( maxLeverage == None ):
            maxLeverage = 1000
        return maxLeverage
    
    def contractsFromUSDT(cls, symbol, amount, price, leverage = 1.0 )->float :
        contractSize = cls.findContractSizeForSymbol( symbol )
        precision = cls.findPrecisionForSymbol( symbol )
        coin = (amount * leverage) / (contractSize * price)
        return roundDownTick( coin, precision ) if ( coin > 0 ) else roundUpTick( coin, precision )
        
    def refreshPositions(cls, v = verbose):
    ### https://docs.ccxt.com/#/?id=position-structure ###
        try:
            positions = cls.exchange.fetch_positions( params = {'settle':'USDT'} ) # the 'settle' param is only required by phemex

        except Exception as e:
            for a in e.args:
                if 'Remote end closed connection' in a :
                    print( timeNow(), cls.exchange.id, '* Refreshpositions:Exception raised: Remote end closed connection' )
                elif '502 Bad Gateway' in a:
                    print( timeNow(), cls.exchange.id, '* Refreshpositions:Exception raised: 502 Bad Gateway' )
                elif 'Internal Server Error' in a:
                    print( timeNow(), cls.exchange.id, '* Refreshpositions:Exception raised: 500 Internal Server Error' )
                #mexc GET https://contract.mexc.com/api/v1/private/position/open_positions
                elif 'mexc GET' in a:
                    print( timeNow(), cls.exchange.id, "* Refreshpositions:Exception raised: couldn't reach mexc GET" )
                elif a == "OK": #Coinex
                    if v : print('Refreshing positions '+cls.accountName+': 0 positions found\n------------------------------' )
                else:
                    print( timeNow(), cls.exchange.id, '* Refreshpositions:Unknown Exception raised:', a )
            return

                    
        # Phemex returns positions that were already closed
        if( cls.exchange.id == "phemex" ):
            # reconstruct the list of positions
            cleanPositionsList = []
            for element in positions:
                thisPosition = cls.exchange.parse_positions( element )[0]
                if( thisPosition.get('contracts') == 0.0 ):
                    continue
                cleanPositionsList.append( thisPosition )
            positions = cleanPositionsList

        numPositions = len(positions)

        if v:
            if( numPositions > 0 ) : print('------------------------------')
            print('Refreshing positions '+cls.accountName+':', numPositions, "positions found" )

        cls.positionslist.clear()
        for thisPosition in positions:

            #HACK!! coinx doesn't have 'contracts'. The value comes in 'contractSize' and in info:{'amount'}
            if( cls.exchange.id == 'coinex' ):
                thisPosition['contracts'] = float( thisPosition['info']['amount'] )

            symbol = thisPosition.get('symbol')
            cls.positionslist.append(position_c( symbol, thisPosition ))

            # if the position contains the marginMode information also update the local data
            if( thisPosition.get('marginMode') != None ) :
                cls.symbolStatus[ symbol ][ 'marginMode' ] = thisPosition.get('marginMode')

            #try also to refresh the leverage from the exchange (not supported by all exchanges)
            if( cls.exchange.has.get('fetchLeverage') == True ):
                response = cls.exchange.fetch_leverage( symbol )

                if( cls.exchange.id == 'bitget' ):
                    # they should always be the same
                    longLeverage = response['data'].get('fixedLongLeverage')
                    shortLeverage = response['data'].get('fixedShortLeverage')
                    if( longLeverage == shortLeverage ):
                        cls.symbolStatus[ symbol ][ 'leverage' ] = longLeverage

                elif( cls.exchange.id == 'bingx' ):
                    # they should always be the same
                    longLeverage = response['data'].get('longLeverage')
                    shortLeverage = response['data'].get('shortLeverage')
                    if( longLeverage == shortLeverage ):
                        cls.symbolStatus[ symbol ][ 'leverage' ] = longLeverage

            elif( thisPosition.get('leverage') != None ):
                leverage = int(thisPosition.get('leverage'))
                if( leverage == thisPosition.get('leverage') ): # kucoin sends weird fractional leverage.
                    cls.symbolStatus[ symbol ][ 'leverage' ] = leverage

        if v:
            for pos in cls.positionslist:
                p = 0.0
                unrealizedPnl = 0 if(pos.getKey('unrealizedPnl') == None) else float(pos.getKey('unrealizedPnl'))
                initialMargin = 0 if(pos.getKey('initialMargin') == None) else float(pos.getKey('initialMargin'))
                collateral = 0.0 if(pos.getKey('collateral') == None) else float(pos.getKey('collateral'))
                if( initialMargin != 0 ):
                    p = ( unrealizedPnl / initialMargin ) * 100.0
                else:
                    p = ( unrealizedPnl / (collateral - unrealizedPnl) ) * 100
                
                print(pos.symbol, pos.getKey('side'), pos.getKey('contracts'), "{:.4f}[$]".format(collateral), "{:.2f}[$]".format(unrealizedPnl), "{:.2f}".format(p) + '%', sep=' * ')
            print('------------------------------')

    def activeOrderForSymbol(cls, symbol ):
        for o in cls.activeOrders:
            if( o.symbol == symbol ):
                return True
        return False
    
    def fetchClosedOrderById(cls, symbol, id ):
        try:
            response = cls.exchange.fetch_closed_orders( symbol, params = {'settleCoin':'USDT'} )
        except Exception as e:
            #Exception: ccxt.base.errors.ExchangeError: phemex {"code":39999,"msg":"Please try again.","data":null}
            return None

        for o in response:
            if o.get('id') == id :
                return o
        if verbose : print( " * fetchPhemexOrderById: Didn't find the [closed] order" )
        return None
    
    def removeFirstCompletedOrder(cls):
        # go through the queue and remove the first completed order
        for order in cls.activeOrders:
            if( order.timedOut() ):
                cls.print( timeNow(), " * Active Order Timed out", order.symbol, order.type, order.quantity, str(order.leverage)+'x' )
                cls.activeOrders.remove( order )
                continue

            # Phemex doesn't support fetch_order in swap mode, but it supports fetch_open_orders and fetch_closed_orders
            if( cls.exchange.id == 'phemex' or cls.exchange.id == 'bybit' ):
                info = cls.fetchClosedOrderById( order.symbol, order.id )
                if( info == None ):
                    continue
            else:
                try:
                    info = cls.exchange.fetch_order( order.id, order.symbol )
                except Exception as e:
                    for a in e.args:
                        if( "does not exist" in a ):
                            cls.activeOrders.remove( order )
                            return
                        
            status = info.get('status')
            remaining = int( info.get('remaining') )
            price = info.get('price')
            if verbose : print( status, 'remaining:', remaining, 'price:', price )

            if( remaining > 0 and (status == 'canceled' or status == 'closed') ):
                print("r...", end = '')
                cls.ordersQueue.append( order_c( order.symbol, order.type, remaining, order.leverage, 0.5 ) )
                cls.activeOrders.remove( order )
                return True
            
            if ( status == 'closed' ):
                cls.print( timeNow(), "* Order succesful:", order.symbol, order.type, order.quantity, str(order.leverage)+"x", "at price", price, 'id', order.id )
                order.quantity = 0
                order.leverage = 0
                cls.activeOrders.remove( order )
                return True
        return False

    def updateOrdersQueue(cls):

        numOrders = len(cls.ordersQueue) + len(cls.activeOrders)

        #see if any active order was completed and delete it
        while cls.removeFirstCompletedOrder():
            continue

        #if we just cleared the orders queue refresh the positions info
        if( numOrders > 0 and (len(cls.ordersQueue) + len(cls.activeOrders)) == 0 ):
            cls.refreshPositions(True)

        if( len(cls.ordersQueue) == 0 ):
            return
        
        # go through the queue activating every symbol that doesn't have an active order
        for order in cls.ordersQueue:
            if( cls.activeOrderForSymbol(order.symbol) ):
                continue

            if( order.timedOut() ):
                cls.print( timeNow(), " * Order Timed out", order.symbol, order.type, order.quantity, str(order.leverage)+'x' )
                cls.ordersQueue.remove( order )
                continue

            if( order.delayed() ):
                continue

            # see if the leverage in the server needs to be changed and setup marginMode/position mode
            cls.updateSymbolLeverage( order.symbol, order.leverage )

            # set up exchange specific parameters
            params = {}

            if( cls.exchange.id == 'kucoinfutures' ):
                params['leverage'] = max( order.leverage, 1 )

            if( cls.exchange.id == 'bitget' ):
                try: #disable hedged mode
                    #response = cls.exchange.set_position_mode( False, order.symbol )
                    params['side'] = 'buy_single' if( order.type == "buy" ) else 'sell_single'
                except Exception as e:
                    cls.print( timeNow(), " * Exception Raised. Failed to set position mode:", e )

                if( order.reverse ): #"reverse":true
                    params['reverse'] = True

            if( cls.exchange.id == 'mexc' ):
                # We could set these up in 'updateSymbolLeverage' but since it can
                # take them it's one less comunication we need to perform
                # openType: 1:isolated, 2:cross - positionMode: 1:hedge, 2:one-way, (no parameter): the user's current config
                params['openType'] = 1
                params['positionMode'] = 2
                params['marginMode'] = 'isolated'
                params['leverage'] = max( order.leverage, 1 )
                # side	int	order direction 1: open long, 2: close short,3: open short 4: close long
                #params['side'] = 1 if( order.type == "buy" ) else 3

            # send the actual order
            try:
                response = cls.exchange.create_market_order( order.symbol, order.type, order.quantity, None, params )
                #print( response )
            
            except Exception as e:
                for a in e.args:
                    if 'Too Many Requests' in a : #set a bigger delay and try again
                        order.delay += 0.5
                        break
                    #
                    # KUCOIN: kucoinfutures Balance insufficient. The order would cost 304.7268292695.
                    # BITGET: bitget {"code":"40762","msg":"The order size is greater than the max open size","requestTime":1689179675919,"data":null}
                    # BITGET: {"code":"40754","msg":"balance not enough","requestTime":1689363604542,"data":null}
                    # [bitget/bitget] bitget {"code":"45110","msg":"less than the minimum amount 5 USDT","requestTime":1689481837614,"data":null}
                    # bingx {"code":101204,"msg":"Insufficient margin","data":{}}
                    # phemex {"code":11082,"msg":"TE_CANNOT_COVER_ESTIMATE_ORDER_LOSS","data":null}
                    # bybit {"retCode":140007,"retMsg":"remark:order[1643476 23006bb4-630a-4917-af0d-5412aaa1c950] fix price failed for CannotAffordOrderCost.","result":{},"retExtInfo":{},"time":1690540657794}
                    
                    elif ( 'Balance insufficient' in a or 'balance not enough' in a 
                          or '"code":"40762"' in a or '"code":"40754" ' in a or '"code":101204' in a
                           or '"code":11082' in a or '"retCode":140007' in a ):
                        precision = cls.findPrecisionForSymbol( order.symbol )
                        # try first reducing it to our estimation of current balance
                        if( not order.reduced ):
                            price = cls.fetchSellPrice(order.symbol) if( type == 'sell' ) else cls.fetchBuyPrice(order.symbol)
                            available = cls.fetchAvailableBalance() * 0.985
                            order.quantity = cls.contractsFromUSDT( order.symbol, available, price, order.leverage )
                            order.reduced = True
                            if( order.quantity < cls.findMinimumAmountForSymbol(order.symbol) ):
                                cls.print( ' * Exception raised: Balance insufficient: Minimum contracts required:', cls.findMinimumAmountForSymbol(order.symbol), ' Cancelling')
                                cls.ordersQueue.remove( order )
                            else:
                                printf( ' * Exception raised: Balance insufficient: Reducing to', order.quantity, "contracts")
                                
                            break
                        elif( order.quantity > precision ):
                            if( order.quantity < 20 and precision >= 1 ):
                                cls.print( ' * Exception raised: Balance insufficient: Reducing by one contract')
                                order.quantity -= precision
                            else:
                                order.quantity = roundDownTick( order.quantity * 0.95, precision )
                                if( order.quantity < cls.findMinimumAmountForSymbol(order.symbol) ):
                                    cls.print( ' * Exception raised: Balance insufficient: Cancelling' )
                                    cls.ordersQueue.remove( order )
                                else:
                                    cls.print( ' * Exception raised: Balance insufficient: Reducing by 5%')
                            break
                        else: #cancel the order
                            cls.print( ' * Exception raised: Balance insufficient: Cancelling')
                            cls.ordersQueue.remove( order )
                            break
                    else:
                        # ToDo
                        cls.print( ' * ERROR Cancelling: Unhandled Exception raised:', e )
                        cls.ordersQueue.remove( order )
                        break
                continue #back to the orders loop

            if( response.get('id') == None ):
                cls.print( "Order denied:", response['info'], "Cancelling" )
                cls.ordersQueue.remove( order )
                continue
            
            order.id = response.get('id')
            if verbose : print( timeNow(), " * Activating Order", order.symbol, order.type, order.quantity, str(order.leverage)+'x', 'id', order.id )
            cls.activeOrders.append( order )
            cls.ordersQueue.remove( order )

accounts = []




def stringToValue( arg )->float:
    if (arg[:1] == "-" ): # this is a minus symbol! What a bitch
        arg = arg[1:]
        return -float(arg)
    else:
        return float(arg)

def is_json( j ):
    try:
        json.loads( j )
    except ValueError as e:
        return False
    return True

def updateOrdersQueue():
    for account in accounts:
        account.updateOrdersQueue()

def refreshPositions():
    for account in accounts:
        account.refreshPositions()

def parseCommandName( token )->str:
    command = 'Invalid'
    if token.lower()  == 'long' or token.lower() == "buy":
        command = 'buy'
    elif token.lower()  == 'short' or token.lower() == "sell":
        command = 'sell'
    elif token.lower()  == 'close':
        command = 'close'
    elif token.lower()  == 'position' or token.lower()  == 'pos':
        command = 'position'
    return command

def parseAlert( data, isJSON, account: account_c ):

    if( account == None ):
        printf( timeNow(), " * ERROR: parseAlert called without an account" )
        return

    symbol = "Invalid"
    quantity = 0
    leverage = 0
    command = "Invalid"
    isUSDT = False
    reverse = False

    # FIXME: json commands are pretty incomplete because I don't use them
    if( isJSON ):
        jdata = json.loads(data)
        for key, value in jdata.items():
            if key == 'ticker' or key == 'symbol':
                if( account.findSymbolFromPairName(value) != None ): # GMXUSDTM, GMX/USDT:USDT and GMX/USDT are all acceptable formats
                    symbol = account.findSymbolFromPairName(value) 
            elif key == 'action' or key == 'command':
                command = parseCommandName(value)
            elif key == 'quantity':
                isUSDT = True
                quantity = stringToValue( value )
            elif key == 'contracts':
                quantity = stringToValue( value )
            elif key == 'leverage':
                leverage = int(value)
    else:
        # Informal plain text syntax
        tokens = data.split()
        for token in tokens:
            if( account.findSymbolFromPairName(token) != None ): # GMXUSDTM, GMX/USDT:USDT and GMX/USDT are all acceptable formats
                symbol = account.findSymbolFromPairName(token) 
            elif ( token == account.accountName ):
                pass
            elif ( token[-1:]  == "$" ):
                isUSDT = True
                arg = token[:-1]
                quantity = stringToValue( arg )
            elif ( token[:1]  == "-" ): # this is a minus symbol! What a bitch
                quantity = stringToValue( token )
            elif ( token.isnumeric() ):
                arg = token
                quantity = float(arg)
            elif ( token[:1].lower()  == "x" ):
                arg = token[1:]
                leverage = int(arg)
            elif ( token[-1:].lower()  == "x" ):
                arg = token[:-1]
                leverage = int(arg)
            elif token.lower()  == 'long' or token.lower() == "buy":
                command = 'buy'
            elif token.lower()  == 'short' or token.lower() == "sell":
                command = 'sell'
            elif token.lower()  == 'close':
                command = 'close'
            elif token.lower()  == 'position' or token.lower()  == 'pos':
                command = 'position'
    

    #let's try to validate the commands
    if( symbol == "Invalid"):
        account.print( "ERROR: Couldn't find symbol" )
        return
    if( command == "Invalid" ):
        account.print( "Invalid Order: Missing command")
        return 
    if( quantity <= 0 and (command == 'buy' or command == 'sell') ):
        account.print( "Invalid Order: Buy/Sell must have positive amount")
        return

    #time to put the order on the queue

    leverage = account.verifyLeverageRange( symbol, leverage )
    available = account.fetchAvailableBalance() * 0.985
    
    # convert quantity to concracts if needed
    if( isUSDT and quantity != 0.0 ) :
        print( "CONVERTING (x"+str(leverage)+")", quantity, "$ ==>", end = '' )
        #We don't know for sure yet if it's a buy or a sell, so we average
        quantity = account.contractsFromUSDT( symbol, quantity, account.fetchAveragePrice(symbol), leverage )
        print( ":", quantity, "contracts" )
        

    #check for a existing position
    pos = account.getPositionBySymbol( symbol )

    if( command == 'close' or (command == 'position' and quantity == 0) ):
        if pos == None:
            printf( timeNow(), " * 'Close", symbol, "' No position found" )
            return
        positionContracts = pos.getKey('contracts')
        positionSide = pos.getKey( 'side' )
        if( positionSide == 'long' ):
            account.ordersQueue.append( order_c( symbol, 'sell', positionContracts, 0 ) )
        else: 
            account.ordersQueue.append( order_c( symbol, 'buy', positionContracts, 0 ) )

        return
    
    # position orders are absolute. Convert them to buy/sell order
    if( command == 'position' ):
        if( pos == None ):
            # it's just a straight up buy or sell
            if( quantity < 0 ):
                command = 'sell'
            else:
                command = 'buy'
            quantity = abs(quantity)
        else:
            #we need to account for the old position
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )
            if( positionSide == 'short' ):
                positionContracts = -positionContracts

            command = 'sell' if positionContracts > quantity else 'buy'
            quantity = abs( quantity - positionContracts )
            if( quantity == 0 ):
                account.print( " * Order completed: Request matched current position")
                return
        # fall through


    if( command == 'buy' or command == 'sell'):

        #fetch available balance and price
        price = account.fetchSellPrice(symbol) if( command == 'sell' ) else account.fetchBuyPrice(symbol)
        canDoContracts = account.contractsFromUSDT( symbol, available, price, leverage )
        minOrder = account.findMinimumAmountForSymbol(symbol)

        if( pos != None ):
            positionContracts = pos.getKey('contracts')
            positionSide = pos.getKey( 'side' )
            
            if ( positionSide == 'long' and command == 'sell' ) or ( positionSide == 'short' and command == 'buy' ):
                reverse = True
                # de we need to divide these in 2 orders?
                if( account.exchange.id == 'bitget' and canDoContracts < account.findMinimumAmountForSymbol(symbol) ): #convert it to a reversal
                    print( "Quantity =", quantity, "PositionContracts=", positionContracts )
                    quantity = positionContracts

                if( quantity >= canDoContracts + positionContracts and not account.canFlipPosition ):
                    # we have to make sure each of the orders has the minimum order contracts
                    order1 = canDoContracts + positionContracts
                    order2 = quantity - (canDoContracts + positionContracts)
                    if( order2 < minOrder ):
                        diff = minOrder - order2
                        if( order1 > minOrder + diff ):
                            order1 -= diff

                    #first order is the contracts in the position and the contracs we can afford with the liquidity
                    account.ordersQueue.append( order_c( symbol, command, order1, leverage ) )

                    #second order is whatever we can affort with the former position contracts + the change
                    quantity -= order1
                    if( quantity >= minOrder ): #we are done (should never happen)
                        account.ordersQueue.append( order_c( symbol, command, quantity, leverage, 1.0 ) )

                    return
            # fall through

        if( quantity < minOrder ):
            account.print( timeNow(), " * ERROR * Order too small:", quantity, "Minimum required:", minOrder )
            return

        account.ordersQueue.append( order_c( symbol, command, quantity, leverage, reverse = reverse ) )
        return

    account.print( timeNow(), " * WARNING: Something went wrong. No order was placed")



def Alert( data ):

    isJSON = is_json(data)

    account = None

    #make a first pass looking for account id
    if( isJSON ):
        jdata = json.loads(data)
        for key, value in jdata.items():
            if key == 'id':
                for a in accounts:
                    if( value == a.id ):
                        account = a
                        break
        if( account == None ):
            if verbose : print( timeNow(), ' * ERROR * Account ID not found.' )
            return
        parseAlert( data, isJSON, account )
        return

    # if plain text accept several alerts separated by line breaks

    #first lets find out if there's more than one commands inside the alert message
    lines = data.split("\n")
    for line in lines:
        account = None
        tokens = line.split()
        for token in tokens:
            for a in accounts:
                if( token == a.accountName ):
                    account = a
                    break
        if( account == None ):
            printf( timeNow(), ' * ERROR * Account ID not found.' )
            return

        parseAlert( line, isJSON, account )




###################
#### Initialize ###
###################

print('----------------------------')

try:
    with open('accounts.json', 'r') as accounts_file:
        accounts_data = json.load(accounts_file)
        accounts_file.close()
except FileNotFoundError:
    with open('accounts.json', 'x') as f:
        f.write( '[\n\t{\n\t\t"EXCHANGE":"kucoinfutures", \n\t\t"ACCOUNT_ID":"your_account_name", \n\t\t"API_KEY":"your_api_key", \n\t\t"SECRET_KEY":"your_secret_key", \n\t\t"PASSWORD":"your_API_password"\n\t}\n]' )
        f.close()
    print( "File 'accounts.json' not found. Template created. Please fill your API Keys into the file and try again")
    print( "Exiting." )
    raise SystemExit()

for ac in accounts_data:

    exchange = ac.get('EXCHANGE')
    if( exchange == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: EXCHANGE" )
        continue

    account_id = ac.get('ACCOUNT_ID')
    if( account_id == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: ACCOUNT_ID" )
        continue

    api_key = ac.get('API_KEY')
    if( api_key == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: API_KEY" )
        continue

    secret_key = ac.get('SECRET_KEY')
    if( secret_key == None ):
        printf( " * ERROR PARSING ACCOUNT INFORMATION: SECRET_KEY" )
        continue

    password = ac.get('PASSWORD')
    if( password == None ):
        password = ""
        continue

    print( timeNow(), " * Initializing account: [", account_id, "] in [", exchange , ']')
    accounts.append( account_c( exchange, account_id, api_key, secret_key, password ) )


if( len(accounts) == 0 ):
    printf( " * FATAL ERROR: No valid accounts found. Please edit 'accounts.json' and introduce your API keys" )
    raise SystemExit()

############################################

#define the webhook server
app = Flask(__name__)
#silencing flask useless spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.disabled = True

@app.route('/whook', methods=['GET','POST'])
def webhook():
    if request.method == 'POST':
        data = request.get_data(as_text=True)
        printf( '\n' + str(timeNow()), "ALERT:", data.replace('\n', ' | ') )
        printf('----------------------------')
        Alert(data)
        return 'success', 200
    if request.method == 'GET':
        wmsg = open( 'webhook.log', encoding="utf-8" )
        text = wmsg.read()
        return app.response_class(text, mimetype='text/plain; charset=utf-8')
    else:
        abort(400)

# start the positions fetching loop
timerFetchPositions = RepeatTimer( 5 * 60, refreshPositions )
timerFetchPositions.start()

timerOrdersQueue = RepeatTimer( 0.25, updateOrdersQueue )
timerOrdersQueue.start()

#start the webhook server
if __name__ == '__main__':
    printf( " * Listening" )
    app.run(host="0.0.0.0", port=80, debug=False)


#timerFetchPositions.cancel()
#timerOrdersQueue.cancel()

